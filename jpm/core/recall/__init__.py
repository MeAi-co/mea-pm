"""
ARCHIVED 2026-08-15 — dead/legacy code audit.
WHY: The RecallHit/RecallQuery/RecallResult facade was never imported by any consumer.
SUPERSEDED BY: jpm.core._hybrid_search.recall_context / _search._search_knowledge.
Kept as a minimal package so `from jpm.core.recall.embeddings import embed_texts`
(used by scripts/sweep_embeddings.py) still resolves.
"""
