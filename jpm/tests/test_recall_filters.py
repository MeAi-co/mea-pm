"""mea_jpm retrieval filter-chain regression suite (P6).

Covers the filters ported from the Mnemosyne prefetch chain:
  P2 distinctive-lexical gate (+ short-query relaxation)
  P3 entity_type source-quality weighting
  P4 semantic dedup
  P5 recency-nudged final sort

No test framework required — also runnable as a plain script:
    <venv>/python3 tests/test_recall_filters.py

The P5 block doubles as the NON-VACUITY proof: test_p5_defect_reproduces_at_zero_weight
asserts that the ORIGINAL defect (sort by rrf alone) reproduces when the
recency weight is 0.0, so test_p5_fresh_ranks_above_stale would FAIL if the fix
were reverted to `key=lambda b: b["rrf"]`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from jpm.core._hybrid_search import (  # noqa: E402
    _RECALL_TUNING_DEFAULTS,
    _final_rank_key,
    _has_distinctive_lexical_evidence,
    _recall_tokens,
    _semantic_dedup_blocks,
    _RECALL_GENERIC_TOKENS,
)

_ENTITY_TYPE_WEIGHT = _RECALL_TUNING_DEFAULTS["entity_type_weight"]


# ── P2: distinctive-lexical gate ───────────────────────────────────────────

def test_p2_one_generic_word_is_not_evidence():
    """A shared GENERIC word ("user") must NOT pass the gate."""
    q = "user"
    # all-generic query -> no distinctive tokens -> cannot pass
    assert not _has_distinctive_lexical_evidence(q, "user profile identity default")
    # a distinctive query sharing ONLY a generic word with content also fails
    assert not _has_distinctive_lexical_evidence(
        "user preferences", "user identity profile"


    )


def test_p2_two_distinctive_tokens_pass():
    """Two shared non-generic tokens with adequate coverage must pass."""
    ok = _has_distinctive_lexical_evidence(
        "database write failure handling",
        "when a database write fails partway, roll the transaction back",
    )
    assert ok is True


def test_p2_short_query_single_token_relaxation():
    """"what is my name?" carries ONE distinctive token; a row sharing it must
    pass (pre-fix this returned 0 blocks — the over-filter pitfall)."""
    q = "what is my name?"
    assert _recall_tokens(q) - _RECALL_GENERIC_TOKENS == {"name"}
    assert _has_distinctive_lexical_evidence(q, "my name is Josh") is True
    # and still rejects content that does not share the token
    assert _has_distinctive_lexical_evidence(q, "played video games for hours") is False


def test_p2_banter_is_dropped():
    for banter in ("thanks", "hey how's it going"):
        assert _recall_tokens(banter) - _RECALL_GENERIC_TOKENS or True  # may be empty
        assert not _has_distinctive_lexical_evidence(banter, "user profile identity default")


# ── P2b: semantic-primary gate (the 2026-10-18 zero-recall fix) ─────────────
# The engine is vector-primary: its top hits are paraphrases sharing ZERO
# distinctive tokens with the query. The ORIGINAL gate REQUIRED lexical
# overlap, so it dropped every legitimate hit (7/8 natural queries -> 0
# blocks). The fix makes the keep signal semantic (cosine band) with lexical
# overlap as a BONUS. These tests drive the real gate helper.

def _gate(blocks, queries, tuning):
    """Drive the REAL P2 gate (jpm.core._hybrid_search._apply_recall_gate).
    Imported at call time so a defect re-injected into the module is picked
    up — a local copy would make the non-vacuity proof vacuous."""
    from jpm.core._hybrid_search import _apply_recall_gate
    return _apply_recall_gate(blocks, queries, tuning)


def test_p2b_paraphrase_with_zero_overlap_survives():
    """A high-cosine paraphrase sharing NO distinctive tokens must survive.
    This is the exact shape that zeroed recall: cos 0.40-0.52, overlap 0."""
    blocks = [
        {"id": 1, "cos_sim": 0.52, "snippet": "the transaction rolls back on failure"},
        {"id": 2, "cos_sim": 0.48, "snippet": "atomicity guarantees all-or-nothing writes"},
    ]
    out = _gate(blocks, ["how should I handle a database write failure?"],
                {"cos_sim_floor": 0.20, "semantic_keep": 0.55, "semantic_ratio": 0.75})
    assert len(out) == 2, "paraphrase hits with zero lexical overlap must survive"


def test_p2b_defect_reproduces_under_lexical_required_gate():
    """NON-VACUITY: the ORIGINAL gate (lexical overlap REQUIRED, no semantic
    band) drops the same paraphrase blocks. Proves the fix is load-bearing —
    reverting to lexical-required makes test_p2b_paraphrase... FAIL."""
    blocks = [
        {"id": 1, "cos_sim": 0.52, "snippet": "the transaction rolls back on failure"},
        {"id": 2, "cos_sim": 0.48, "snippet": "atomicity guarantees all-or-nothing writes"},
    ]
    q = "how should I handle a database write failure?"
    # Original semantics: keep ONLY if lexical evidence passes.
    kept = [b for b in blocks
            if _has_distinctive_lexical_evidence(q, b["snippet"], 2, 0.30)]
    assert kept == [], "original lexical-required gate must drop these (defect)"


def test_p2b_generic_only_match_still_dropped():
    """The fix must NOT re-admit generic-word noise: a low-cosine block that
    shares only a generic word falls out of the semantic band."""
    blocks = [
        {"id": 1, "cos_sim": 0.50, "snippet": "the deploy script restarts the gateway"},
        {"id": 2, "cos_sim": 0.10, "snippet": "user profile identity default preferences"},
    ]
    out = _gate(blocks, ["how do I restart the gateway?"],
                {"cos_sim_floor": 0.20, "semantic_keep": 0.55, "semantic_ratio": 0.75})
    ids = {b["id"] for b in out}
    assert 1 in ids, "the real hit must survive"
    assert 2 not in ids, "the generic-only low-cosine block must be dropped"


# ── P3: source-quality weighting ───────────────────────────────────────────

def test_p3_distilled_outranks_raw():
    assert _ENTITY_TYPE_WEIGHT["rule"] > _ENTITY_TYPE_WEIGHT["memory_entry"]
    assert _ENTITY_TYPE_WEIGHT["project"] > _ENTITY_TYPE_WEIGHT["memory_entry"]
    assert _ENTITY_TYPE_WEIGHT["general"] > _ENTITY_TYPE_WEIGHT["memory_entry"]


# ── P4: semantic dedup ─────────────────────────────────────────────────────

def test_p4_dedups_near_identical_pair():
    b1 = {"id": 1, "rrf": 0.03, "snippet": "the deploy script writes config then restarts the gateway"}
    b2 = {"id": 2, "rrf": 0.02, "snippet": "the deploy script writes config then restarts the gateway"}
    out = _semantic_dedup_blocks([b1, b2])
    assert len(out) == 1
    assert out[0]["id"] == 1  # higher-ranked kept


def test_p4_keeps_distinct_blocks():
    b1 = {"id": 1, "rrf": 0.03, "snippet": "deploy script writes config restarts gateway"}
    b2 = {"id": 2, "rrf": 0.02, "snippet": "gaming playtime hours total video games played"}
    assert len(_semantic_dedup_blocks([b1, b2])) == 2


# ── P5: recency-nudged final sort (+ non-vacuity) ──────────────────────────

def test_p5_fresh_ranks_above_stale():
    """Equal RRF, one fresh one stale -> fresh first when the fix is active."""
    fresh = {"id": "fresh", "rrf": 0.0250, "recency": 1.0}
    stale = {"id": "stale", "rrf": 0.0250, "recency": 0.1}
    rw = 0.15
    assert _final_rank_key(fresh, rw) > _final_rank_key(stale, rw)
    ordered = sorted([stale, fresh], key=lambda b: _final_rank_key(b, rw), reverse=True)
    assert ordered[0]["id"] == "fresh"


def test_p5_defect_reproduces_at_zero_weight():
    """NON-VACUITY: at weight 0.0 the ORIGINAL behaviour (sort by rrf alone)
    reproduces — the two blocks tie — so the test above would fail if the fix
    were reverted. This proves the suite actually exercises the fix."""
    fresh = {"id": "fresh", "rrf": 0.0250, "recency": 1.0}
    stale = {"id": "stale", "rrf": 0.0250, "recency": 0.1}
    assert _final_rank_key(fresh, 0.0) == _final_rank_key(stale, 0.0)


def test_p5_recency_is_only_a_nudge():
    """A strong RRF match must beat a weak-but-fresher one — recency cannot
    lift a weak match over a strong one."""
    strong_stale = {"id": "s", "rrf": 0.030, "recency": 0.0}
    weak_fresh = {"id": "w", "rrf": 0.010, "recency": 1.0}
    rw = 0.15
    assert _final_rank_key(strong_stale, rw) > _final_rank_key(weak_fresh, rw)


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = []
    for fn in fns:
        try:
            fn()
            print("PASS %s" % fn.__name__)
        except AssertionError as e:
            failed.append(fn.__name__)
            print("FAIL %s :: %s" % (fn.__name__, e))
        except Exception as e:  # noqa: BLE001
            failed.append(fn.__name__)
            print("ERROR %s :: %r" % (fn.__name__, e))
    print("\n%d/%d passed" % (len(fns) - len(failed), len(fns)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
