"""Async live-embed worker — embeds new rows on write, non-blocking.

Design goals:
  1. NEVER block the critical write path on Ollama.  enqueue() is
     fire-and-forget; the caller's commit never waits on embedding.
  2. NEVER flood PG with connections.  Workers own a small, dedicated
     set of psycopg2 connections (one per worker thread), separate from
     the gateway's asyncpg pool, so they can't poison a pooled
     connection or disturb pool accounting.
  3. NEVER leave rows stale.  Three layers: (a) in-queue retry with
     backoff, (b) bounded queue that drops to the watchdog on overflow,
     (c) the watchdog reconciler catches anything the worker missed
     (gateway died, Ollama down long, batch import bypassed the hook).
  4. NEVER waste a GPU round-trip.  Workers drain UP TO BATCH rows per
     Ollama HTTP call and write them back in a single multi-row
     transaction, instead of one request per row.  A small pool of
     workers runs concurrent in-flight batches, so sustained traffic
     (many agents x many end users) spreads across both GPUs instead of
     queueing behind a single-threaded loop.

Writes use the SAME idempotent shape as scripts/embed_watchdog.py:
    UPDATE <table> SET embedding = v.embedding,
        embedding_model = v.model, embedding_updated_at = v.ts
    FROM (VALUES ...) AS v(embedding, model, ts, id) WHERE t.id = v.id

It can't corrupt anything: single idempotent UPDATE per row, clean
commits, no partial writes, no duplicates.

Usage:
    from jpm.core._embed_worker import enqueue
    enqueue("messages", msg_id, text)   # fire-and-forget
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from ._ollama import embed as ollama_embed

log = logging.getLogger("jpm.embed_worker")

# ── Config (env-driven, same defaults as the watchdog) ──────────────────
MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
DIM = int(os.environ.get("EMBED_DIM", "768"))
BATCH = int(os.environ.get("EMBED_BATCH", "32"))
NUM_GPU = int(os.environ.get("EMBED_NUM_GPU", "-1"))
MODEL_TAG = f"{MODEL}:latest"

# Bounded queue: if it overflows (Ollama down for a long stretch, or a
# write burst that outpaces the pool), we drop the oldest and let the
# watchdog reconciler pick the row up later.  Sized generously for peak
# traffic (multiple agents + multiple end users).
MAX_QUEUE = int(os.environ.get("EMBED_QUEUE", "8000"))
# Retry backoff for Ollama failures (seconds, exponential).
MAX_RETRY = int(os.environ.get("EMBED_MAX_RETRY", "5"))
# Concurrent worker threads.  Each holds one PG connection and one
# in-flight batched embed.  Kept modest (default 2) so Ollama receives
# concurrent batches but we don't saturate the embed endpoint with tiny
# HTTP calls.
WORKERS = max(1, int(os.environ.get("EMBED_WORKERS", "2")))

# Tables we know how to embed and their text-surface builders.
_TEXT_BUILDERS: dict[str, Any] = {}


def _text_knowledge(row: dict) -> str:
    parts = [row.get("name"), row.get("description")]
    return "\n".join(p for p in parts if p and p.strip())[:8000]


def _text_message(row: dict) -> str:
    parts = [row.get("content"), row.get("tool_name")]
    return "\n".join(p for p in parts if p and p.strip())[:8000]


def _text_skill(row: dict) -> str:
    parts = [row.get("name"), row.get("description"), row.get("content")]
    return "\n".join(p for p in parts if p and p.strip())[:8000]


def _text_skill_section(row: dict) -> str:
    parts = [row.get("heading"), row.get("body")]
    return "\n".join(p for p in parts if p and p.strip())[:8000]


_TEXT_BUILDERS = {
    "knowledge": _text_knowledge,
    "messages": _text_message,
    "skills": _text_skill,
    "skill_sections": _text_skill_section,
}


def _vec_str(v: list[float]) -> str:
    """Render a vector in pgvector's canonical text form: [0.1,0.2,...]."""
    return "[" + ",".join(str(x) for x in v) + "]"


# ── The worker pool ─────────────────────────────────────────────────────
class _EmbedWorker:
    """Bounded queue + a pool of worker threads, each with a dedicated
    PG connection and batched, multi-row Ollama embedding."""

    def __init__(self) -> None:
        self._q: "queue.Queue[Optional[tuple[str, int, str]]]" = queue.Queue(maxsize=MAX_QUEUE)
        self._threads: list[threading.Thread] = []
        self._started = False
        self._lock = threading.Lock()

    # -- public API ------------------------------------------------------
    def enqueue(self, table: str, row_id: int, text: str) -> bool:
        """Fire-and-forget. Returns True if queued, False if dropped (overflow)."""
        if table not in _TEXT_BUILDERS:
            return False
        if row_id is None:
            # A None id can never match `WHERE t.id = v.id` (bigint = text).
            # Refuse it here so a caller bug can't poison the batch.
            log.warning("embed enqueue refused: %s row_id is None", table)
            return False
        if not text or not text.strip():
            return False
        self._ensure_started()
        try:
            self._q.put_nowait((table, row_id, text))
            return True
        except queue.Full:
            # Drop oldest to bound memory; the watchdog reconciler catches it.
            try:
                self._q.get_nowait()
                self._q.put_nowait((table, row_id, text))
            except queue.Full:
                pass
            log.warning("embedding queue full — dropped row %s:%s (watchdog will catch)", table, row_id)
            return False

    def _ensure_started(self) -> None:
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            for i in range(WORKERS):
                t = threading.Thread(
                    target=self._run, name=f"embed-worker-{i}", daemon=True
                )
                t.start()
                self._threads.append(t)
            self._started = True
            log.info(
                "embedding worker pool started: %d workers, batch=%d, queue=%d",
                WORKERS, BATCH, MAX_QUEUE,
            )

    # -- internals -------------------------------------------------------
    def _run(self) -> None:
        conn = None
        while True:
            try:
                item = self._q.get()
            except Exception:
                continue
            if item is None:
                break
            conn = self._get_conn(conn)
            # Drain up to BATCH rows into one batch.
            batch = [item]
            for _ in range(BATCH - 1):
                try:
                    nxt = self._q.get_nowait()
                    if nxt is None:
                        # Sentinel received mid-drain: stop draining so the
                        # remaining workers observe the shutdown token too.
                        break
                    batch.append(nxt)
                except queue.Empty:
                    break
            try:
                self._process_batch(conn, batch)
            except Exception as exc:
                log.warning(
                    "embed worker batch error (%d rows): %s", len(batch), exc
                )
                # The connection may be dead (stale socket / server restarted).
                # Close it and drop our reference so the next iteration
                # reconnects fresh instead of retrying on the same dead conn.
                conn = self._drop_conn(conn)
                for it in batch:
                    self._retry_or_queue(*it)

    def _get_conn(self, conn):
        """Return a usable connection, reconnecting if ours is gone/stale."""
        if conn is not None:
            try:
                # Fast liveness probe. If the server closed the socket, this
                # raises immediately instead of blocking on a stale conn.
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.close()
                return conn
            except Exception:
                # Defunct — fall through and reconnect.
                conn = self._drop_conn(conn)
        return self._connect()

    def _drop_conn(self, conn):
        """Best-effort close, then return None so callers reconnect."""
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        return None

    def _connect(self):
        import psycopg2

        return psycopg2.connect(
            host=os.environ.get("JPM_PG_HOST", "127.0.0.1"),
            port=os.environ.get("JPM_PG_PORT", "5432"),
            user=os.environ.get("JPM_PG_USER", "postgres"),
            password=os.environ.get("JPM_PG_PASSWORD", ""),
            dbname=os.environ.get("JPM_PG_DB", "jpm"),
        )

    def _process_batch(self, conn, batch) -> None:
        """Embed a batch of (table, row_id, text) and write them back in a
        single multi-row UPDATE per table."""
        texts = [t for (_, _, t) in batch]
        vectors = self._embed(texts)
        if not vectors or len(vectors) != len(batch):
            raise RuntimeError(
                f"embedding returned {len(vectors) if vectors else 0} vectors for {len(batch)} rows"
            )
        # Group by table so each UPDATE targets one table.
        by_table: dict[str, list[tuple[int, str]]] = {}
        for (tbl, _rid, _text), vec in zip(batch, vectors):
            by_table.setdefault(tbl, []).append((_rid, _vec_str(vec)))

        cur = conn.cursor()
        for tbl, rows in by_table.items():
            value_rows = ", ".join(
                ["(%s::vector, %s, %s, %s)"] * len(rows)
            )
            params: list[Any] = []
            for rid, vec_s in rows:
                params.extend([vec_s, MODEL_TAG, datetime.now(timezone.utc), rid])
            sql = (
                f"UPDATE {tbl} t SET embedding = v.embedding, "
                f"embedding_model = v.model, embedding_updated_at = v.ts "
                f"FROM (VALUES {value_rows}) AS v(embedding, model, ts, id) "
                f"WHERE t.id = v.id"
            )
            cur.execute(sql, params)
        conn.commit()
        cur.close()

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Primary→fallback failover handled by _ollama.embed()
        for attempt in range(4):
            try:
                return ollama_embed(texts)
            except Exception as exc:
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
        return []

    def _retry_or_queue(self, table: str, row_id: int, text: str) -> None:
        # Simple bounded retry: requeue up to MAX_RETRY times, then drop to
        # the watchdog.  The watchdog is the guarantee, so a bounded requeue
        # is sufficient.
        for _ in range(MAX_RETRY):
            try:
                self._q.put_nowait((table, row_id, text))
                return
            except queue.Full:
                time.sleep(1)
        log.warning(
            "embed worker gave up on %s:%s after %d retries — watchdog will catch",
            table, row_id, MAX_RETRY,
        )


# ── Module-level singleton ───────────────────────────────────────────────
_worker = _EmbedWorker()


def enqueue(table: str, row_id: int, text: str) -> bool:
    """Fire-and-forget embed request. Never blocks on Ollama or PG."""
    return _worker.enqueue(table, row_id, text)


def shutdown() -> None:
    """Stop the worker pool (used on gateway shutdown)."""
    for _ in range(WORKERS):
        try:
            _worker._q.put_nowait(None)
        except queue.Full:
            pass
