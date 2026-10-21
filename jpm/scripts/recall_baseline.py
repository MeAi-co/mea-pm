#!/usr/bin/env python3
"""P0 baseline harness for mea_jpm retrieval upgrade.

Calls the REAL entry point (jpm.core._hybrid_search.recall_context) over a fixed
query set and dumps every returned block's ranking signals to JSON.

Design notes (why this is not a tautology):
  - We drive recall_context() itself, with the same signature the live
    per-turn hook uses (_hooks.py pre_llm_call -> tables=[knowledge,
    reflections, patterns]). We do NOT reconstruct inputs or stub helpers.
  - We record rrf / cos_sim / score(recency) exactly as the engine emits them,
    so a before/after diff shows what the filter chain changed.

Usage:
  recall_baseline.py [--out PATH] [--ts TS] [--limit N]

Env: JOSHAICO_HOME must point at the arm home (so config + .env resolve).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# Make the vendored jpm package importable when run as a bare script.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))  # .../plugins/mea_pm
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

# Recall tables the live path passes (memory_enrichment.tables default).
RECALL_TABLES = ["knowledge", "reflections", "patterns"]

# Fixed query set — >=10, spanning the four classes the brief calls for:
#   topical-no-overlap (relevant rows share no lexical tokens with the query)
#   topical-overlap    (relevant rows share tokens)
#   entity-resolution  (named entity lookup)
#   banter/light       (should recall nothing / very little)
QUERIES = [
    # --- 3x topical-no-overlap ---
    {"q": "how should I handle it when a database write fails partway through?",
     "class": "topical_no_overlap",
     "expect": ["knowledge:5", "knowledge:6", "knowledge:7", "patterns:1"]},
    {"q": "what is the safest way to make sure a claim is actually true before I save it?",
     "class": "topical_no_overlap",
     "expect": ["knowledge:49", "patterns:4"]},
    {"q": "how do I report an exact figure instead of a rough guess?",
     "class": "topical_no_overlap",
     "expect": ["knowledge:48", "knowledge:54", "knowledge:56", "patterns:6"]},
    # --- 3x topical-overlap ---
    {"q": "how many hours have I played video games in total?",
     "class": "topical_overlap",
     "expect": ["knowledge:10", "knowledge:11", "knowledge:12", "knowledge:47",
                "knowledge:50", "knowledge:51", "knowledge:52", "knowledge:57"]},
    {"q": "what is my name?",
     "class": "topical_overlap",
     "expect": ["knowledge:4"]},
    {"q": "which video games have I played?",
     "class": "topical_overlap",
     "expect": ["knowledge:50", "knowledge:51", "knowledge:52"]},
    # --- 2x entity-resolution ---
    {"q": "Josh gaming playtime total",
     "class": "entity_resolution",
     "expect": ["knowledge:4", "knowledge:11", "knowledge:50", "knowledge:51", "knowledge:52"]},
    {"q": "skill db write fallback",
     "class": "entity_resolution",
     "expect": ["knowledge:5", "knowledge:6", "knowledge:7"]},
    # --- 2x banter / light ---
    {"q": "thanks",
     "class": "banter",
     "expect": []},
    {"q": "hey how's it going",
     "class": "banter",
     "expect": []},
]


def _run_once(queries, limit):
    from jpm.core._hybrid_search import recall_context

    out = []
    for item in queries:
        q = item["q"]
        t0 = time.time()
        try:
            blocks = recall_context(
                q, limit=limit, session_id="", tables=list(RECALL_TABLES)
            )
        except Exception as e:  # never let one query kill the run
            out.append({
                "query": q,
                "class": item["class"],
                "expected": item["expect"],
                "error": f"{type(e).__name__}: {e}",
                "blocks": [],
                "elapsed_s": round(time.time() - t0, 3),
            })
            continue
        out.append({
            "query": q,
            "class": item["class"],
            "expected": item["expect"],
            "error": None,
            "blocks": [
                {
                    "table": b.get("table"),
                    "id": b.get("id"),
                    "title": (b.get("title") or "")[:120],
                    "rrf": b.get("rrf"),
                    "cos_sim": b.get("cos_sim"),
                    "score": b.get("score"),      # recency boost (pre-P1)
                    "recency": b.get("recency"),  # post-P1 rename
                    "tag": b.get("tag"),
                }
                for b in (blocks or [])
            ],
            "elapsed_s": round(time.time() - t0, 3),
        })
    return out


def _id_set(result):
    return sorted(f"{b['table']}:{b['id']}" for b in result["blocks"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--ts", default=None)
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--label", default="baseline")
    args = ap.parse_args()

    ts = args.ts or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = args.out or f"/opt/bench/results/recall_{args.label}_{ts}.json"

    # Determinism check: run the set twice, compare (table,id) sets per query.
    run1 = _run_once(QUERIES, args.limit)
    run2 = _run_once(QUERIES, args.limit)

    determinism = []
    for a, b in zip(run1, run2):
        same = _id_set(a) == _id_set(b)
        determinism.append({
            "query": a["query"],
            "same_ids": same,
            "run1": _id_set(a),
            "run2": _id_set(b),
        })

    # Recall quality vs the hand-labelled expectations.
    scoring = []
    for item in run1:
        got = set(_id_set(item))
        exp = set(item["expected"])
        hit = sorted(got & exp)
        scoring.append({
            "query": item["query"],
            "class": item["class"],
            "n_blocks": len(item["blocks"]),
            "n_expected": len(exp),
            "n_hit": len(hit),
            "hits": hit,
            "missed": sorted(exp - got),
            "extra": sorted(got - exp),
        })

    payload = {
        "meta": {
            "ts": ts,
            "label": args.label,
            "limit": args.limit,
            "tables": RECALL_TABLES,
            "joshaico_home": os.environ.get("JOSHAICO_HOME"),
            "entry_point": "jpm.core._hybrid_search.recall_context",
            "n_queries": len(QUERIES),
        },
        "results": run1,
        "determinism": determinism,
        "scoring": scoring,
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    # Console summary.
    print(f"wrote {out_path}")
    ndet = sum(1 for d in determinism if d["same_ids"])
    print(f"determinism: {ndet}/{len(determinism)} queries stable")
    tot_exp = sum(s["n_expected"] for s in scoring)
    tot_hit = sum(s["n_hit"] for s in scoring)
    print(f"recall vs expectations: {tot_hit}/{tot_exp} expected ids recalled")
    for s in scoring:
        print(f"  [{s['class']:<20}] n={s['n_blocks']} hit={s['n_hit']}/{s['n_expected']}"
              f"  {s['query'][:52]!r}")
        if s["missed"]:
            print(f"       missed: {s['missed']}")


if __name__ == "__main__":
    main()
