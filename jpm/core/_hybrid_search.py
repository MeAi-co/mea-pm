"""Hybrid semantic search for JPM — vector-primary recall with an FTS crutch.

Design:
  - Vector recall is the PRIMARY path. The query is embedded via Ollama
    (OLLAMA_URL env), the HNSW index is searched (embedding <=> query_vec),
    and the top matches are fetched by id. Semantic results are authoritative
    and are NOT gated behind a lexical match.
  - FTS (websearch_to_tsquery / ILIKE) is a LAST-RESORT net, reached only when
    the embedding column is absent, Ollama is unreachable, or the vector path
    returned nothing. It never swallows semantic results.
  - RRF formula: score = Σ 1/(k + rank), k=60.

Graceful degradation: if pgvector / embedding column / Ollama is missing,
falls back to pure FTS. Never raises.
"""

import json
import logging
import os
import re
import time

from ._ollama import embed_query
from ._pg import sync_conn

LOG = logging.getLogger("jpm.hybrid_search")

EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
RRF_K = 60
MIN_FTS_RESULTS = 3  # if FTS returns fewer than this, do vector recall

# ── Recall tuning (2026-08-14) ────────────────────────────────────────
# Knowledge breadcrumbs are the primary recall target (auto-mined every
# turn), so they get a relevance boost in the cross-table RRF merge while
# raw message/session matches are slightly penalized — durable lessons
# float up, raw-transcript noise sinks.
_KNOWLEDGE_RRF_BOOST = 1.5
_MESSAGE_RRF_PENALTY = 0.8

# ── retrieval filter chain (ported from the Mnemosyne prefetch chain) ──
# Module-level defaults so recall_context/_sweep_queries work when called
# without an explicit tuning dict (e.g. the P0 baseline harness). The live
# per-turn path passes the values read from memory_enrichment config via
# _hooks._enrichment_config(); these are the fail-open fallbacks.
_RECALL_TUNING_DEFAULTS = {
    "min_distinctive_tokens": 2,   # P2: >=N non-generic shared tokens
    "min_query_coverage": 0.30,    # P2: overlap/len(query_tokens) floor
    "rrf_floor": 0.0,              # P2: RRF floor (paired with cos_sim_floor)
    "cos_sim_floor": 0.20,         # P2: drop only when BOTH floors fail
    "semantic_keep": 0.55,         # P2: cos_sim that rescues a block w/o lexical overlap
    "semantic_ratio": 0.75,        # P2: keep blocks within this ratio of the best cos
    "candidate_pool": 0,           # P2: pre-gate over-fetch; 0 => max(limit*3, 12)
    "dedup_jaccard": 0.72,         # P4: jaccard dup threshold
    "dedup_containment": 0.86,     # P4: containment dup threshold
    "recency_weight": 0.15,        # P5: recency nudge weight in final sort
    # P3: per-entity_type weight for knowledge rows — distilled types rank
    # above raw transcript-derived ones. Multiplies the knowledge RRF
    # contribution so it composes with rank (applied inside the accumulation,
    # not as a post-sort multiplier). Unknown types default to 1.0.
    "entity_type_weight": {
        "rule": 1.15,
        "project": 1.12,
        "general": 1.10,
        "tool": 1.05,
        "system": 1.05,
        "memory_entry": 0.90,
    },
}

# P2: generic schema/system labels that do NOT by themselves prove relevance.
# Mirrors Mnemosyne's _PREFETCH_LEXICAL_GENERIC_TOKENS.
_RECALL_GENERIC_TOKENS = frozenset({
    "user", "owner", "assistant", "agent", "system", "profile", "identity",
    "default", "preference", "preferences", "recommendation", "recommendations",
})

# P2/P4: tokenizer + stopword set for the lexical gate and semantic dedup.
_RECALL_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE | re.UNICODE)
_RECALL_STOPWORDS = frozenset({
    "the", "and", "for", "with", "are", "you", "your", "her", "his", "she",
    "he", "its", "this", "that", "these", "those", "there", "here", "then",
    "than", "also", "into", "onto", "about", "would", "could", "should",
    "will", "shall", "can", "not", "but", "or", "if", "so", "do", "does",
    "did", "is", "am", "was", "were", "be", "been", "being", "have", "has",
    "had", "it", "me", "my", "mine", "we", "us", "our", "they", "them",
    "their", "what", "when", "which", "where", "how", "why", "who", "whom",
    "after", "before", "because", "from", "like", "more", "need", "needs",
    "want", "wants", "while", "yourself", "get", "got", "make", "made",
})
# NOTE (2026-09-03): the score floors (_CONTEXT_SCORE_FLOOR / _RELATIVE /
# _COS) were removed. The LLM already judged relevance when it wrote the
# recall queries; the vector search returns matches for exactly those terms.
# A second rank-normalization + score-floor gate re-judged that work with a
# heuristic that can't understand the conversation — and it collapsed to 0
# when a single candidate survived the type gate (the top match's rank term
# normalized to 0, dropping it below the floor). The RRF merge below is the
# real relevance ranking; no fake score re-gates it.

# Regex matching a nested [Context: JPM CONTEXT "..." (...): ...] wrapper so
# a recalled snippet that is itself a stored breadcrumb gets de-nested
# before injection (kills the compounding artifact). The meta parens can
# contain one level of nesting (e.g. "(0.48 @ 2026-07-10 17:56 (1mo ago))"),
# so the paren group allows balanced inner parens.
_CONTEXT_WRAPPER_RE = re.compile(
    r"\[Context:\s*JPM\s+CONTEXT\s+\"[^\"]*\"\s*"
    r"\((?:[^()]|\([^()]*\))*\)\s*:\s*\]?\s*",
    re.IGNORECASE,
)


def strip_context(text: str) -> str:
    """Strip nested [Context: JPM CONTEXT ...] wrappers from a snippet.

    A recalled knowledge row whose description is itself a stored breadcrumb
    string gets re-injected verbatim, producing
    ``[Context: JPM CONTEXT "X" (0.48): [Context: JPM CONTEXT "X" (0.48): ...]]``.
    This removes the outer wrapper(s) — including their closing ``]`` — so
    only the inner content survives.
    """
    if not text:
        return text
    prev = None
    cur = text
    # Iterate until stable — nested wrappers can be several layers deep.
    while cur != prev:
        prev = cur
        # Count how many opening wrappers this pass removes, then drop the
        # same number of trailing ']' (each wrapper contributes one closing
        # bracket that the opening regex does not consume).
        n_removed = len(_CONTEXT_WRAPPER_RE.findall(cur))
        stripped = _CONTEXT_WRAPPER_RE.sub("", cur).strip()
        if n_removed and stripped.endswith("]"):
            stripped = stripped[: -min(n_removed, stripped.count("]"))].rstrip()
        cur = stripped
    return cur

# ── Hybrid capability gate ─────────────────────────────────────────────
# Default-ON with capability auto-detect. Hybrid search is the standard
# behavior everywhere; it only turns off when (a) explicitly disabled via
# JPM_HYBRID_SEARCH=0, or (b) the vector stack (embedding column) isn't
# deployed. Degradation is NEVER silent — we log loudly on every fallback.
_HYBRID_CACHE = None  # None = undetermined, True/False = cached result


def hybrid_enabled() -> bool:
    """Default-on hybrid search with capability auto-detect.

    Returns True unless:
      - JPM_HYBRID_SEARCH=0 explicitly disables it, OR
      - the pgvector embedding column isn't deployed on this node.

    The result is cached after first check so we don't re-probe the DB
    on every search. Falls back to FTS in code, but logs loudly here so
    degradation is never silent.
    """
    global _HYBRID_CACHE

    # Explicit opt-out wins (only value that disables; anything else = on)
    if os.environ.get("JPM_HYBRID_SEARCH") == "0":
        LOG.warning("jpm: hybrid search explicitly disabled (JPM_HYBRID_SEARCH=0) — using FTS only")
        return False

    # Capability auto-detect (cached after first probe)
    if _HYBRID_CACHE is None:
        try:
            with sync_conn() as conn:
                col = conn.fetchone(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'knowledge' AND column_name = 'embedding'"
                )
                _HYBRID_CACHE = bool(col)
        except Exception as e:
            LOG.warning("jpm: hybrid capability check failed, defaulting to FTS: %s", e)
            _HYBRID_CACHE = False
        if not _HYBRID_CACHE:
            LOG.warning(
                "jpm: pgvector embedding column NOT found — hybrid search DISABLED, "
                "using FTS only. (Set JPM_HYBRID_SEARCH=1 to force, or deploy pgvector.)"
            )
        else:
            LOG.info("jpm: hybrid search ENABLED (pgvector detected)")

    return _HYBRID_CACHE


# The nomic-embed-text-v1.5 model has a HARD 2048-token context ceiling
# (the llama.cpp backends 400 on any single input > n_ctx; only Ollama used to
# silently truncate instead). The recall/planner query path has NO char cap —
# the `_recall_planner` [message] fallback can ship a giant raw user turn here
# and 503. Clamp every recall query to ~1850 tokens so it can never breach the
# 2048-token model wall. Budget uses a conservative ~3 chars/token so even dense
# code stays safely under. Truncation affects only the ephemeral recall query
# (never a stored vector), so the semantic gist of the search is preserved.
_EMBED_QUERY_MAX_CHARS = 5500  # ≈1850 tokens at 3 chars/token


def _embed_query(query: str) -> list[float] | None:
    """Embed a single query via Ollama (primary→fallback). Returns vector or None on failure.

    Clamps the query to _EMBED_QUERY_MAX_CHARS before embedding so a giant
    planner fallback query (``queries = [message]``) can never exceed nomic's
    hard 2048-token context ceiling and 503.
    """
    if query and len(query) > _EMBED_QUERY_MAX_CHARS:
        LOG.warning(
            "jpm: recall query truncated for embedding %d -> %d chars "
            "(nomic 2048-token ctx ceiling)",
            len(query), _EMBED_QUERY_MAX_CHARS,
        )
        query = query[:_EMBED_QUERY_MAX_CHARS]
    return embed_query(query)


def _vector_search_ids(
    table: str,
    query_vec: list[float],
    limit: int,
    offset: int = 0,
    where_sql: str = "",
    params: tuple = (),
) -> list[tuple[int, float]]:
    """Search the HNSW index for the closest row ids, returning (id, cosine_distance).

    Returns a list of ``(id, distance)`` tuples ordered by ascending cosine
    distance (best first). The distance is the *real* pgvector ``<=>`` output
    (0 = identical, 1 = orthogonal, 2 = opposite) — callers that want a true
    semantic filter can use it as an absolute gate instead of relying on
    batch-relative rank. The distance was historically discarded (only ids
    returned), which is why the recall pipeline had no absolute semantic
    floor and dragged in loose numeric-measurement neighbors whenever the
    whole batch was weak.

    ``where_sql`` (optional) is an additional SQL fragment injected into the
    WHERE clause — used by callers that need to scope vector recall to the
    same filters as the FTS path (role, source, active/compacted, content
    filter). It must reference the table alias used by the caller (for
    messages that is ``m``). ``params`` are the matching parameter tuple.

    For the knowledge table, archived rows (archived=1) are excluded so a
    soft-deleted breadcrumb stops surfacing in recall — otherwise the
    usefulness feedback loop's archive step would be a no-op.
    """
    try:
        with sync_conn() as conn:
            vec_literal = "[" + ",".join(f"{v:.6f}" for v in query_vec) + "]"
            clause = f"WHERE embedding IS NOT NULL"
            if table == "knowledge":
                clause += " AND m.archived = 0"
            if where_sql:
                clause += f" AND {where_sql}"
            # Profile scope goes last so caller params keep their order.
            if table == "knowledge":
                from ._profile import knowledge_scope

                _scope_sql, _scope_params = knowledge_scope("m")
                clause += f" AND {_scope_sql}"
                params = tuple(params or ()) + tuple(_scope_params)
            rows = conn.fetchall(
                f"SELECT m.id, m.embedding <=> '{vec_literal}'::vector AS dist "
                f"FROM {table} m "
                f"{clause} "
                f"ORDER BY dist "
                f"LIMIT {limit} OFFSET {offset}",
                params,
            )
            return [(r["id"], float(r["dist"])) for r in rows]
    except Exception as e:
        LOG.warning("vector search failed (falling back to FTS-only): %s", e)
        return []


def _fetch_rows_by_ids(table: str, ids: list[int]) -> dict[int, dict]:
    """Fetch full row shapes for the given ids, keyed by id.

    Reuses _search_knowledge's row shape: id, title (aliased from name),
    plus desc/weightage/time/entity_type where they exist.
    """
    from ._search import TABLE_CONFIG

    if not ids:
        return {}
    cfg = TABLE_CONFIG.get(table)
    if not cfg:
        return {}
    text_cols, has_fts, id_col, title_col, ts_col, weight_col, time_col, desc_col, _emb_col, _emb_text, _filter_col = cfg

    _select_cols = [f"{id_col} as id", f"{title_col} as title"]
    if desc_col:
        _select_cols.append(desc_col)
    if weight_col:
        _select_cols.append(weight_col)
    if time_col:
        _select_cols.append(time_col)
    if table == "knowledge":
        _select_cols.append("entity_type")

    _select_sql = ", ".join(_select_cols)
    placeholders = ", ".join("?" for _ in ids)
    _scope_sql, _scope_params = "1 = 1", []
    if table == "knowledge":
        from ._profile import knowledge_scope

        _scope_sql, _scope_params = knowledge_scope()
    try:
        with sync_conn() as conn:
            rows = conn.fetchall(
                f"SELECT {_select_sql} FROM {table} WHERE {id_col} IN ({placeholders}) AND {_scope_sql}",
                tuple(ids) + tuple(_scope_params),
            )
            return {r["id"]: dict(r) for r in rows}
    except Exception as e:
        LOG.warning("fetch rows by ids failed (falling back to FTS-only): %s", e)
        return {}


def _rff_merge(
    fts_rows: list[dict],
    vec_ids: list[int],
    rows_by_id: dict[int, dict],
    limit: int,
) -> list[dict]:
    """Reciprocal Rank Fusion over FTS + vector result sets."""
    scores: dict[int, float] = {}
    for rank, r in enumerate(fts_rows):
        scores[r["id"]] = scores.get(r["id"], 0.0) + 1.0 / (RRF_K + rank + 1)
    for rank, rid in enumerate(vec_ids):
        scores[rid] = scores.get(rid, 0.0) + 1.0 / (RRF_K + rank + 1)

    merged_ids = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    merged = []
    for rid, score in merged_ids:
        row = rows_by_id.get(rid) or next((r for r in fts_rows if r["id"] == rid), None)
        if row:
            # Attach the computed RRF score onto the returned row so callers
            # (hybrid_search_knowledge -> provider prefetch) can rank/gate on
            # it. Previously the score was computed then discarded.
            row["rrf"] = score
            merged.append(row)
    return merged


def hybrid_search_knowledge(
    query: str,
    limit: int = 10,
    offset: int = 0,
    table: str = "knowledge",
) -> tuple[list[dict], bool]:
    """Vector-primary hybrid search.

    Vector recall is the primary path (the semantic win). FTS is only used
    as a last-resort net when embeddings / Ollama are unavailable — never as
    a gate that swallows semantic results.
    """
    from ._search import _search_knowledge

    try:
        with sync_conn() as conn:
            col_check = conn.fetchone(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = ? AND column_name = 'embedding'",
                (table,),
            )
            if not col_check:
                # No pgvector deployed — fall back to FTS as a crutch
                fts_results, has_more = _search_knowledge(query, limit, offset, table)
                return fts_results, has_more
    except Exception as e:
        LOG.warning("hybrid_search_knowledge col check failed: %s", e)
        fts_results, has_more = _search_knowledge(query, limit, offset, table)
        return fts_results, has_more

    # 1. Vector recall — the primary semantic path
    query_vec = _embed_query(query)
    if query_vec:
        vec_hits = _vector_search_ids(table, query_vec, limit + 1, offset)
        if vec_hits:
            vec_ids = [rid for rid, _dist in vec_hits]
            # Fetch one extra row to compute has_more correctly
            has_more = len(vec_ids) > limit
            vec_ids = vec_ids[:limit]
            rows_by_id = _fetch_rows_by_ids(table, vec_ids)
            # Vector-only RRF (no FTS gate) — semantic results are authoritative
            merged = _rff_merge([], vec_ids, rows_by_id, limit)
            if merged:
                return merged, has_more

    # 2. FTS crutch — only reached when embedding/vector path failed or was empty
    fts_results, has_more = _search_knowledge(query, limit, offset, table)
    return fts_results, has_more


# ═══════════════════════════════════════════════════════════════════════
# Unified cross-table semantic recall (recall_context)
# ═══════════════════════════════════════════════════════════════════════

# Tables to sweep on every recall, in priority order.
# All 6 embedded tables: knowledge, messages, sessions, reflections,
# patterns, skills. imgen_library is profile-specific (image-gen telemetry) and
# is deliberately excluded from the general recall sweep — it's not relevant
# to cross-agent context injection. projects/tasks have no embedding column.
RECALL_TABLES = ["knowledge", "messages", "sessions", "reflections", "patterns", "skills"]
RECALL_PER_TABLE = 12  # per-table hits pulled before cross-table RRF trim

# Cache of which RECALL_TABLES actually have an embedding column on this node.
# None = undetermined, else a list of table names. Probed once, then reused so
# recall_context doesn't re-query information_schema (or eat exceptions for
# tables that don't exist / lack pgvector) on every single recall.
_RECALL_TABLES_CACHE: list[str] | None = None


def _recall_tables_with_embedding(tables: list[str] | None = None) -> list[str]:
    """Return the subset of the requested tables that have an embedding column.

    ``tables`` defaults to RECALL_TABLES (the full sweep). Callers that want a
    scoped auto-recall (e.g. knowledge/reflections/patterns only for per-turn
    enrichment — no message/session log noise, no skills already injected in
    the system prompt) pass an explicit allowlist.

    The probe always covers ALL RECALL_TABLES and caches the full available
    set, then filters by the caller's allowlist. This guarantees the cache is
    allowlist-agnostic: a scoped first call (knowledge/reflections/patterns)
    still probes messages/sessions/skills, so a later full-sweep call can never
    miss tables just because an earlier call asked for a narrower scope. The
    probe is a cheap information_schema check; the expensive part is the vector
    sweep, which is only ever run on the caller's allowlist.

    Some nodes don't deploy every table (e.g. imgen_library is profile-specific)
    or lack the pgvector column on a given table (e.g. skills). Sweeping those
    unconditionally makes recall_context log a warning and run a doomed query
    on every call. This probes information_schema once, caches the result, and
    lets recall_context skip tables that can't participate in vector recall.
    """
    # Distinguish None (caller wants the full sweep) from an explicit [] (caller
    # wants NO tables — sweep nothing). Also tolerate a scalar string by
    # wrapping it, so `tables: knowledge` isn't silently iterated as characters.
    if tables is None:
        tables = RECALL_TABLES
    elif isinstance(tables, str):
        tables = [tables]
    elif not isinstance(tables, (list, tuple)):
        tables = RECALL_TABLES
    key = set(t for t in tables if isinstance(t, str))
    # An explicit empty allowlist means "sweep nothing".
    if not key:
        return []

    global _RECALL_TABLES_CACHE
    if _RECALL_TABLES_CACHE is None:
        available = []
        try:
            with sync_conn() as conn:
                for table in RECALL_TABLES:
                    try:
                        col = conn.fetchone(
                            "SELECT 1 FROM information_schema.columns "
                            "WHERE table_name = ? AND column_name = 'embedding'",
                            (table,),
                        )
                        if col:
                            available.append(table)
                    except Exception:
                        # Table missing or unreadable — skip it silently.
                        continue
        except Exception as e:
            LOG.warning("recall_context: embedding-column probe failed: %s", e)
            available = []
        _RECALL_TABLES_CACHE = available
        if len(available) != len(RECALL_TABLES):
            missing = [t for t in RECALL_TABLES if t not in available]
            LOG.info(
                "recall_context: skipping tables without embedding column: %s",
                ", ".join(missing),
            )

    # Filter the (allowlist-agnostic) full cache by the caller's allowlist.
    return [t for t in _RECALL_TABLES_CACHE if t in key]


def _recency_boost(table: str, row: dict) -> float:
    """Return a recency multiplier in (0, 1] based on the row's time column.

    Fresher rows get a higher boost so the most recent relevant memory
    surfaces first — this is what makes recall feel like 'she just knows'.
    """
    time_col = {"sessions": "started_at", "messages": "timestamp",
                "reflections": "created_at", "patterns": "last_fired",
                "knowledge": "last_referenced", "skills": "updated_at",
                "imgen_library": "created_at"}.get(table)
    if not time_col or time_col not in row or not row[time_col]:
        return 1.0
    try:
        ts = row[time_col]
        if isinstance(ts, (int, float)):
            epoch = ts
        else:
            epoch = ts.timestamp()
        age_days = (time.time() - epoch) / 86400.0
    except Exception:
        return 1.0
    # Decay: 1.0 today, ~0.5 at 30 days, floor at 0.2
    return max(0.2, 1.0 / (1.0 + age_days / 30.0))


def _recall_tokens(text: str) -> set[str]:
    """Lowercase word tokens with stopwords + generic labels stripped.

    Used by the P2 distinctive-lexical gate and the P4 semantic dedup. Mirrors
    Mnemosyne's _prefetch_tokens: drop tokens <=2 chars and the stopword set.
    """
    if not text:
        return set()
    toks = set()
    for t in _RECALL_TOKEN_RE.findall(text.lower()):
        t = t.strip(".,;!?()[]{}\"'")
        if len(t) <= 2 or t in _RECALL_STOPWORDS:
            continue
        toks.add(t)
    return toks


def _has_distinctive_lexical_evidence(
    query: str,
    content: str,
    min_tokens: int = 2,
    min_coverage: float = 0.30,
) -> bool:
    """True when query and content share >=min_tokens non-generic terms AND
    that overlap covers >=min_coverage of the query's distinctive tokens.

    Ported from Mnemosyne's _prefetch_has_distinctive_lexical_evidence. A
    single generic shared word (e.g. "user") is NOT evidence of relevance.
    """
    q_tokens = _recall_tokens(query) - _RECALL_GENERIC_TOKENS
    if not q_tokens:
        # Query is all-generic (e.g. "thanks") — no distinctive evidence is
        # possible, so the gate cannot pass. Callers treat this as "drop".
        return False
    overlap = q_tokens & _recall_tokens(content)
    # A short query may carry only ONE distinctive token ("what is my name?"
    # -> {"name"}); demanding min_tokens=2 there would drop every legitimate
    # row that query has. Require at most as many shared tokens as the query
    # actually offers. (Mnemosyne gates its full-message query, which always
    # has enough tokens; our queries are the short per-turn user message, so
    # this relaxation is required — see the over-filter pitfall.)
    required = min(min_tokens, len(q_tokens))
    return (
        len(overlap) >= required
        and (len(overlap) / max(len(q_tokens), 1)) >= min_coverage
    )


def _apply_recall_gate(
    blocks: list[dict],
    queries: list[str],
    tuning: dict,
) -> list[dict]:
    """P2 gate: keep a block when it is semantically OR lexically relevant.

    SEMANTIC-PRIMARY. This engine is vector-primary: its top hits are
    paraphrases that share NO distinctive tokens with the query (verified
    2026-10-18: 7/8 natural queries returned blocks with overlap=0 at
    cos 0.40-0.52). A gate that REQUIRES lexical overlap therefore drops every
    legitimate hit — it silently disabled recall. So the primary keep signal
    is semantic: a block survives when its cosine clears the absolute
    ``semantic_keep`` rescue, or sits within ``semantic_ratio`` of the batch's
    BEST match (the top semantic band), or carries distinctive lexical
    evidence. Lexical evidence is a BONUS keep, never a requirement.
    Generic-word noise is still excluded: a generic-only match has low cosine
    and falls out of the band.

    Extracted to module level so the regression suite drives THIS function
    (not a copy) — a duplicated gate in the test would be vacuous.
    """
    cos_floor = float(tuning.get("cos_sim_floor", 0.0))
    semantic_keep = float(tuning.get("semantic_keep", 0.0))
    sem_ratio = float(tuning.get("semantic_ratio", 0.75))
    min_tok = int(tuning.get("min_distinctive_tokens", 2))
    min_cov = float(tuning.get("min_query_coverage", 0.30))
    distinctive_qs = [
        q for q in queries if _recall_tokens(q) - _RECALL_GENERIC_TOKENS
    ]
    best_cos = max((b.get("cos_sim", 0.0) for b in blocks), default=0.0)
    keep_floor = max(cos_floor, best_cos * sem_ratio)
    gated: list[dict] = []
    for b in blocks:
        cos = b.get("cos_sim", 0.0)
        # Absolute semantic rescue (high-confidence paraphrase).
        if semantic_keep > 0.0 and cos >= semantic_keep:
            gated.append(b)
            continue
        # Relative semantic band — the primary keep for a vector-primary sweep.
        if keep_floor > 0.0 and cos >= keep_floor:
            gated.append(b)
            continue
        # Lexical bonus keep: distinctive overlap with the best sub-query.
        if not distinctive_qs:
            continue
        snip_tokens = _recall_tokens(b.get("snippet") or "")
        best_q, best_overlap = None, -1
        for q in distinctive_qs:
            ov = len((_recall_tokens(q) - _RECALL_GENERIC_TOKENS) & snip_tokens)
            if ov > best_overlap:
                best_overlap, best_q = ov, q
        if best_q is not None and _has_distinctive_lexical_evidence(
            best_q, b.get("snippet") or "", min_tok, min_cov
        ):
            gated.append(b)
    return gated


def _final_rank_key(block: dict, recency_weight: float) -> float:
    """P5 ranking key: RRF relevance nudged by recency.

    ``recency_weight`` = 0 reproduces the pre-fix behaviour (sort by rrf
    alone) exactly, so the non-vacuity test can re-inject the original defect
    by passing 0.0. Recency multiplies by a value in (0,1], so it can only
    reorder near-equal RRF scores — it can never lift a weak match over a
    strong one.
    """
    rrf = float(block.get("rrf", 0.0) or 0.0)
    recency = float(block.get("recency", 1.0) or 0.0)
    return rrf * (1.0 + recency_weight * recency)


def _semantic_dedup_blocks(
    blocks: list[dict],
    threshold: float = 0.72,
    containment: float = 0.86,
) -> list[dict]:
    """Drop near-duplicate blocks (same tokens, different id), keeping the
    higher-ranked one. Ported from Mnemosyne's _semantic_dedup_prefetch.

    Blocks are assumed pre-sorted best-first; the first of a duplicate pair is
    kept. Uses jaccard >= threshold OR containment >= containment.
    """
    kept: list[dict] = []
    kept_tokens: list[set[str]] = []
    for b in blocks:
        toks = _recall_tokens(b.get("snippet") or "")
        if not toks:
            kept.append(b)
            continue
        dup = False
        for existing in kept_tokens:
            overlap = len(toks & existing)
            if not overlap:
                continue
            jaccard = overlap / max(len(toks | existing), 1)
            contain = overlap / max(min(len(toks), len(existing)), 1)
            if jaccard >= threshold or contain >= containment:
                dup = True
                break
        if dup:
            continue
        kept.append(b)
        kept_tokens.append(toks)
    return kept


def _build_context_block(
    table: str,
    rid,
    conn=None,
    session_matches: dict[str, int] | None = None,
) -> dict | None:
    """Build a compact human-readable context block for a recalled row.

    Pass a shared `conn` to reuse one pooled connection across many rows
    (recall_context hot path); when omitted, a fresh connection is used.
    ``session_matches`` maps a session id -> count of vector-similar messages
    surfaced in this sweep, so a session/message block can report
    "N similar matches in this thread" instead of first/last bookends.
    """
    from ._search import TABLE_CONFIG

    cfg = TABLE_CONFIG.get(table)
    if not cfg:
        return None
    _, _hfts, id_col, title_col, _tsc, weight_col, time_col, desc_col, _emb_col, _emb_text, _filter_col = cfg

    def _fetch(conn):
        _sel = [f"{id_col} as id", f"{title_col} as title"]
        if desc_col:
            _sel.append(desc_col)
        if time_col:
            _sel.append(time_col)
        if table == "knowledge":
            _sel.append("entity_type")
        if table == "messages":
            _sel.append("session_id")
        return conn.fetchone(
            f"SELECT {', '.join(_sel)} FROM {table} WHERE {id_col} = ?",
            (rid,),
        )

    try:
        if conn is not None:
            row = _fetch(conn)
        else:
            with sync_conn() as conn:
                row = _fetch(conn)
        if not row:
            return None
        row = dict(row)
    except Exception as e:
        LOG.warning("recall block fetch failed (%s/%s): %s", table, rid, e)
        return None

    title = (row.get("title") or "").strip()
    body = ""
    session_id = row.get("session_id") if table == "messages" else (str(rid) if table == "sessions" else None)
    if desc_col and row.get(desc_col):
        body = str(row[desc_col])
    elif table == "knowledge":
        body = title
    elif table == "sessions":
        body = title  # session blocks use the N-matches count, not bookends
    elif table == "messages":
        body = title  # title_col == content for messages
    elif table == "reflections":
        body = title  # title_col == insight
    elif table == "patterns":
        body = (row.get("description") or title)

    snippet = (body or "").strip()
    if not snippet:
        return None
    # De-nest: a recalled row whose body is itself a stored breadcrumb
    # string gets stripped of its [Context: JPM CONTEXT ...] wrapper(s) so
    # the compounding artifact doesn't re-inject verbatim.
    snippet = strip_context(snippet)
    if not snippet:
        return None
    if len(snippet) > 400:
        snippet = snippet[:397] + "..."

    # For a session/message block, surface how many vector-similar messages
    # this sweep found in the same thread. Tells the agent how much relevant
    # material actually lives there — richer than a first/last bookend peek.
    thread_count = None
    if session_id:
        thread_count = (session_matches or {}).get(session_id) or 1

    tag = table.upper()
    if table == "knowledge" and row.get("entity_type"):
        tag = f"{tag}[{row['entity_type']}]"
        # Gate at the source: core standard types already
        # live in the system prompt via memory injection. Recalling them into
        # the user message is bloat AND makes the model treat them as the
        # active directive, diverging from the task. Only breadcrumbs
        # (general, memory_entry, project, tool, system, etc.) ride in.
        if row["entity_type"] in ("rule", "dna", "identity", "soul", "user_pref"):
            return None
    boost = _recency_boost(table, row)

    # Surface the row's timestamp in an agent-readable form so the model
    # can judge how recent the memory is. Raw epoch would be noise; a
    # compact ISO + relative age reads clearly in a breadcrumb.
    time_label = None
    if time_col and time_col in row and row[time_col]:
        raw_ts = row[time_col]
        try:
            if isinstance(raw_ts, (int, float)):
                from datetime import datetime
                dt = datetime.fromtimestamp(raw_ts)
            else:
                dt = raw_ts
                if dt.tzinfo is not None:
                    # Stored values are naive local (system time). If a value
                    # carries an offset (legacy UTC), normalize to naive local
                    # so .timestamp() and the age math stay in the same frame.
                    dt = dt.astimezone().replace(tzinfo=None)
            iso = dt.strftime("%Y-%m-%d %H:%M")
            age_days = max(0.0, (time.time() - dt.timestamp()) / 86400.0)
            if age_days < 1.0:
                rel = f"{int(age_days * 24)}h ago"
            elif age_days < 30.0:
                rel = f"{int(age_days)}d ago"
            elif age_days < 365.0:
                rel = f"{int(age_days // 30)}mo ago"
            else:
                rel = f"{int(age_days // 365)}y ago"
            time_label = f"{iso} ({rel})"
        except Exception:
            time_label = str(raw_ts)[:19]

    return {
        # "recency" is the recency multiplier in (0,1] — a freshness signal,
        # NOT a relevance score. Renamed from "score" (2026-10-18) because the
        # old name collided with the RRF relevance ranking and was never read
        # by any consumer; every reader uses rrf/cos_sim for relevance.
        "recency": boost,
        "tag": tag,
        "title": title,
        "snippet": snippet,
        "time": time_label,
        "session_id": session_id,
        "thread_count": thread_count,
        "table": table,
        "id": rid,
    }


# ARCHIVED 2026-08-15 — dead code audit: _session_bookend_snippet has zero callers.
# Candidate for wiring into _hooks._bookend_session later. Kept per archive-don't-delete rule.
def _session_bookend_snippet(session_id: str, conn=None) -> str:
    """For a session, surface first + last messages as the recall body."""
    def _run(conn):
        rows = conn.fetchall(
            "SELECT id FROM messages WHERE session_id = ? "
            "AND role IN ('user','assistant') ORDER BY id ASC LIMIT 1",
            (session_id,),
        )
        first_id = rows[0]["id"] if rows else None
        rows = conn.fetchall(
            "SELECT id FROM messages WHERE session_id = ? "
            "AND role IN ('user','assistant') ORDER BY id DESC LIMIT 1",
            (session_id,),
        )
        last_id = rows[0]["id"] if rows else None
        if not first_id:
            return ""
        start_messages = conn.fetchall(
            "SELECT role, content FROM messages WHERE session_id = ? "
            "AND id >= ? ORDER BY id ASC LIMIT 2",
            (session_id, first_id),
        )
        end_rows = conn.fetchall(
            "SELECT role, content FROM messages WHERE session_id = ? "
            "AND id <= ? ORDER BY id DESC LIMIT 2",
            (session_id, last_id),
        ) if last_id else []
        return first_id, last_id, start_messages, list(reversed(end_rows))

    try:
        if conn is not None:
            result = _run(conn)
        else:
            with sync_conn() as conn:
                result = _run(conn)
    except Exception:
        return ""

    if not result:
        return ""
    first_id, last_id, start_messages, end_messages = result

    parts = []
    for m in start_messages:
        snip = (m["content"] or "")[:140].replace("\n", " ")
        if snip:
            parts.append(f"{m['role']}: {snip}")
    if last_id:
        parts.append(f"...")
    for m in end_messages:
        snip = (m["content"] or "")[:140].replace("\n", " ")
        if snip:
            parts.append(f"{m['role']}: {snip}")
    return " | ".join(parts)


def recall_context(
    query: str,
    limit: int = 8,
    session_id: str | None = None,
    history: list[dict] | None = None,
    tables: list[str] | None = None,
    queries: list[str] | None = None,
    tuning: dict | None = None,
) -> list[dict]:
    """Unified vector-primary semantic recall across all memory tables.

    Embeds the query ONCE, sweeps all 5 HNSW indexes in parallel, RRF-merges
    cross-table on (table, id) composite keys, recency-weights, and returns
    the top-k most relevant context blocks regardless of table.

    This is the engine behind adaptive JPM context injection — the agent is
    fed the nearest-neighbor matches to the *current* query each turn.

    Multi-topic awareness: when the query looks multi-topic (long + shift
    markers), an optional LLM query-planner (repurposed from the retired FTS5
    smart_refine loop) classifies the message and splits it into 3-6
    self-contained, scope-aware vector queries. Each is embedded and swept
    separately, then the per-query result sets are RRF-merged together — so a
    paragraph about "agencies, models, AND a KFT business plan" surfaces the
    KFT context it would otherwise dilute away. Light message types
    (banter/emotional/intimate/smalltalk) skip heavy recall entirely.
    ``session_id`` is passed through so the planner can scope to the current
    conversation. Any planner failure degrades to the single-vector fast path,
    so recall is never worse than today.

    ``queries`` (optional) bypasses the LLM planner entirely. When the caller
    already has planned query terms (e.g. produced in-band by the warm main
    model), pass them here and the cold `_call_refinement_llm` planner is
    skipped — the sweep runs directly on the given queries. This is the
    in-band recall path: no second model call, no 15s timeout, no cold KV.

    ``tables`` (optional) restricts the vector sweep to the given allowlist of
    memory tables. Per-turn enrichment passes knowledge/reflections/patterns so
    raw message/session history (which re-injects the query verbatim and
    inflates context) and skills (already injected into the system prompt) are
    excluded from the hot path.

    Returns a list of {"score", "tag", "title", "snippet", "time",
    "session_id", "thread_count"} dicts.
    ``time`` is an agent-readable timestamp ("2026-08-10 05:30 (3h ago)") or
    None when the row has no time column. ``session_id`` is set for message
    rows (so the agent can open the thread), and ``thread_count`` reports how
    many vector-similar messages the sweep surfaced in that same thread —
    replacing first/last bookends with "N similar matches in this thread".
    Never raises.
    """
    _explicit_queries = queries is not None
    queries = queries or [query]
    try:
        from ._recall_planner import looks_light, plan_recall
        # When the caller already produced planned query terms in-band (warm
        # main model), skip BOTH the light-type veto and the cold LLM planner
        # — the warm model already judged intent deliberately. Trust its
        # queries; no second model call, no 15s timeout, no cheap heuristic
        # overriding the warm verdict. Skills = recipe, breadcrumbs = context,
        # and both fire on every message — so a short/banter/emotional message
        # that the warm planner decided deserves context still gets it.
        if _explicit_queries:
            return _sweep_queries(queries, tables, limit, tuning=tuning)
        # Cheap light-type gate for the DEFAULT (non-planned) path: short
        # emotional / banter / intimate messages skip recall entirely without
        # an LLM call. This catches "it just hurts" and terse confirmations
        # ("sure", "ok") so they are never hijacked by the loudest recent
        # breadcrumb.
        if looks_light(query):
            return []
        # Run the LLM planner on ALL messages (not just long multi-topic
        # ones). Short / ambiguous conversational follow-ups ("the context
        # looks lame", "the changes show?") are exactly where prior-turn
        # context matters most — a raw single-vector sweep of the bare
        # message dumps loud system trivia at high confidence. The planner
        # gets the previous 2-3 user + 2-3 completed assistant responses to
        # judge intent, and its type + query verdict decides injection:
        #   - banter/emotional/intimate/smalltalk -> empty queries -> nothing
        #   - clear directives -> scoped queries -> relevant context
        plan = plan_recall(query, session_id=session_id, history=history)
        if plan.get("planner"):
            # Empty queries means a light type (banter/emotional/intimate/
            # smalltalk) — skip heavy recall entirely. plan_recall guarantees
            # non-empty queries for work types (falls back to [message]), so
            # planner=True + empty queries ⟺ light type ⟺ skip.
            planned = plan.get("queries") or []
            if not planned:
                return []
            queries = planned
    except Exception as e:
        LOG.debug("recall_context: planner skipped (%s) — single-vector path", e)

    return _sweep_queries(queries, tables, limit, tuning=tuning)


def _sweep_queries(
    queries: list[str],
    tables: list[str] | None,
    limit: int,
    tuning: dict | None = None,
) -> list[dict]:
    """Sweep the given queries across the vector indexes and RRF-merge the hits.

    Shared by both recall paths: the cold LLM planner's planned queries and
    the in-band warm-model queries. Embeds each query once, sweeps the HNSW
    indexes in parallel, RRF-merges cross-table on (table, id) composite
    keys, recency-weights, and returns the top-k context blocks. Never raises.
    """
    # Sweep across all planned queries and RRF-merge the per-query hits.
    # ``tables`` (optional) scopes the sweep to a caller-chosen allowlist —
    # per-turn enrichment passes knowledge/reflections/patterns so message/session
    # log noise and skills (already injected in the system prompt) don't bloat
    # the context block or the embed+vector cost.
    table_hits: dict[str, list] = {}
    # Map (table, id) -> best (lowest) cosine distance seen across queries.
    # This is the *real* semantic similarity (0=tight, 1=orthogonal) — it is
    # threaded into the final score and an absolute floor so a weak batch
    # can't drag loose neighbors past the cut purely by rank.
    cos_sim_map: dict[tuple, float] = {}
    tables = _recall_tables_with_embedding(tables)
    for q in queries:
        query_vec = _embed_query(q)
        if not query_vec:
            continue
        for table in tables:
            try:
                hits = _vector_search_ids(table, query_vec, RECALL_PER_TABLE)
                if hits:
                    # Merge across queries: keep the union, tag rank per query.
                    existing = table_hits.get(table, [])
                    merged = list(dict.fromkeys(existing + [rid for rid, _d in hits]))
                    table_hits[table] = merged
                    # Keep the best (lowest) distance per (table, id).
                    for rid, dist in hits:
                        key = (table, rid)
                        cur = cos_sim_map.get(key)
                        if cur is None or dist < cur:
                            cos_sim_map[key] = dist
            except Exception as e:
                LOG.warning("recall_context: sweep %s failed: %s", table, e)

    if not table_hits:
        return []

    # Resolve tuning: caller-supplied dict wins, else module defaults.
    t = dict(_RECALL_TUNING_DEFAULTS)
    if tuning:
        t.update({k: v for k, v in tuning.items() if v is not None})

    # P3: entity_type weight map (config-overridable; fail-open to defaults).
    _etw = t.get("entity_type_weight")
    if not isinstance(_etw, dict):
        _etw = _RECALL_TUNING_DEFAULTS["entity_type_weight"]

    # P3: fetch entity_type for the knowledge ids that survived the sweep so
    # the RRF accumulation can weight distilled types above raw ones.
    _entity_type_map: dict[int, str] = {}
    _k_ids = table_hits.get("knowledge") or []
    if _k_ids:
        try:
            with sync_conn() as conn:
                ph = ",".join("?" for _ in _k_ids)
                rows = conn.fetchall(
                    f"SELECT id, entity_type FROM knowledge WHERE id IN ({ph})",
                    tuple(_k_ids),
                )
                for r in rows:
                    if r["entity_type"]:
                        _entity_type_map[int(r["id"])] = str(r["entity_type"])
        except Exception as e:
            LOG.debug("recall_context: entity_type map failed: %s", e)

    # 2. Cross-table RRF merge on (table, id) composite keys.
    #    Knowledge breadcrumbs get a relevance boost (they're the primary
    #    recall target — auto-mined every turn), raw message/session matches
    #    a slight penalty, so durable lessons float up over transcript noise.
    #    P3: knowledge rows are further weighted by entity_type (distilled
    #    types rank above raw transcript-derived ones) — applied INSIDE the
    #    accumulation so it composes with rank rather than overriding it.
    scores: dict[tuple, float] = {}
    for table, ids in table_hits.items():
        weight = 1.0
        if table == "knowledge":
            weight = _KNOWLEDGE_RRF_BOOST
        elif table in ("messages", "sessions"):
            weight = _MESSAGE_RRF_PENALTY
        for rank, rid in enumerate(ids):
            key = (table, rid)
            w = weight
            if table == "knowledge":
                et = _entity_type_map.get(rid)
                if et:
                    w = weight * _etw.get(et, 1.0)
            scores[key] = scores.get(key, 0.0) + w / (RRF_K + rank + 1)

    # P2 needs a candidate pool larger than the final limit: the gate drops
    # rows, so cutting to `limit` FIRST leaves too few survivors (measured:
    # 5 -> 0 blocks on a 5-token query). Over-fetch, gate, then trim to limit.
    pool = int(t.get("candidate_pool", 0) or 0)
    if pool <= 0:
        pool = max(limit * 3, 12)
    merged_keys = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:pool]

    # 3. Count how many vector-similar MESSAGES each session contributed, so
    #    session/message blocks can report "N similar matches in this thread".
    #    Only needed when the messages table participated in the sweep.
    session_matches: dict[str, int] = {}
    if "messages" in table_hits:
        msg_ids = table_hits.get("messages", [])
        if msg_ids:
            try:
                with sync_conn() as conn:
                    ph = ",".join("?" for _ in msg_ids)
                    rows = conn.fetchall(
                        f"SELECT session_id, COUNT(*) AS n "
                        f"FROM messages WHERE id IN ({ph}) GROUP BY session_id",
                        tuple(msg_ids),
                    )
                    for r in rows:
                        if r["session_id"]:
                            session_matches[str(r["session_id"])] = int(r["n"])
            except Exception as e:
                LOG.debug("recall_context: session-match count failed: %s", e)

    # 4. Build context blocks with recency weighting applied.
    #    One shared connection for the whole batch — no per-row pool churn.
    blocks = []
    with sync_conn() as conn:
        for (table, rid), rrf_score in merged_keys:
            block = _build_context_block(
                table,
                rid,
                conn=conn,
                session_matches=session_matches,
            )
            if block:
                block["rrf"] = rrf_score
                # Attach the real semantic distance (0=tight, 1=orthogonal)
                # surfaced by the sweep, and convert to a similarity in (0,1]
                # so it can blend with the normalized RRF term. Rows that
                # never came from the vector path (FTS-only degradation) get
                # a neutral 1.0 distance so they're not unfairly gated.
                dist = cos_sim_map.get((table, rid), 1.0)
                block["cos_sim"] = max(0.0, 1.0 - dist)
                blocks.append(block)

    # 5. P2 relevance floor + distinctive-lexical gate.
    #    A block survives when EITHER its RRF clears the floor OR its cosine
    #    similarity clears the cos floor — a weak batch can't drag loose
    #    neighbors past the cut purely by rank. On top of that, the block must
    #    share >=min_distinctive_tokens non-generic terms with the BEST
    # 5. P2 relevance floor + distinctive-lexical gate (see _apply_recall_gate).
    gated = _apply_recall_gate(blocks, queries, t)

    # 6. P4 semantic dedup — drop near-duplicate blocks (same tokens, different
    #    id), keeping the higher-ranked one. Runs after the gate so we dedup
    #    the survivors, not the raw candidate set.
    deduped = _semantic_dedup_blocks(
        gated,
        threshold=float(t.get("dedup_jaccard", 0.72)),
        containment=float(t.get("dedup_containment", 0.86)),
    )

    # 7. P5 final sort: RRF relevance nudged by recency. The RRF merge already
    #    ranked blocks by how well they matched the recall queries — that IS
    #    the relevance judgment. Recency is a small tie-break nudge (weight
    #    from config), NOT a re-judgment: it can reorder near-equal RRF scores
    #    but cannot lift a weak match over a strong one. The old code computed
    #    a recency boost in _build_context_block and then DISCARDED it by
    #    sorting on rrf alone; this applies it.
    rw = float(t.get("recency_weight", 0.0))
    deduped.sort(key=lambda b: _final_rank_key(b, rw), reverse=True)

    return deduped[:limit]


# ═══════════════════════════════════════════════════════════════════════
# Hybrid message recall (messages() tool + session_search discovery)
# ═══════════════════════════════════════════════════════════════════════

def hybrid_message_ids(
    query: str,
    limit: int = 20,
    offset: int = 0,
    where_sql: str = "",
    params: tuple = (),
) -> tuple[list[int], bool]:
    """Vector recall over the messages table, returning ranked message ids.

    Mirrors hybrid_search_knowledge's graceful degradation: returns
    (empty, False) when embeddings/Ollama are unavailable so the caller
    falls back to pure FTS. ``where_sql`` scopes vector recall to the same
    filters as the FTS path (role, source, active/compacted, content
    filter) — it may reference the ``m`` (messages) and ``s`` (sessions)
    aliases, matching the FTS query's join scope.
    """
    try:
        with sync_conn() as conn:
            col_check = conn.fetchone(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'messages' AND column_name = 'embedding'",
            )
            if not col_check:
                return [], False
    except Exception as e:
        LOG.warning("hybrid_message_ids col check failed: %s", e)
        return [], False

    query_vec = _embed_query(query)
    if not query_vec:
        return [], False

    try:
        with sync_conn() as conn:
            vec_literal = "[" + ",".join(f"{v:.6f}" for v in query_vec) + "]"
            # JOIN sessions whenever the filter scope references it, so
            # source/exclude filters keep working on the vector path.
            if "s." in (where_sql or ""):
                from_sql = "FROM messages m JOIN sessions s ON s.id = m.session_id"
            else:
                from_sql = "FROM messages m"
            clause = "WHERE m.embedding IS NOT NULL"
            if where_sql:
                clause += f" AND {where_sql}"
            rows = conn.fetchall(
                f"SELECT m.id {from_sql} "
                f"{clause} "
                f"ORDER BY m.embedding <=> '{vec_literal}'::vector "
                f"LIMIT {limit} OFFSET {offset}",
                params,
            )
            ids = [r["id"] for r in rows]
    except Exception as e:
        LOG.warning("hybrid message vector search failed: %s", e)
        return [], False

    if not ids:
        return [], False
    has_more = len(ids) > limit
    return ids[:limit], has_more
