import logging

from ._pg import sync_conn

LOG = logging.getLogger("jpm.read")


def _get_latest_pulse() -> dict | None:
    try:
        with sync_conn() as conn:
            row = conn.fetchone("SELECT status, summary, created_at FROM pulse ORDER BY created_at DESC LIMIT 1")
            return dict(row) if row else None
    except Exception as e:
        LOG.error("_get_latest_pulse failed: %s", e, exc_info=True)
        return None


def _get_active() -> dict | None:
    try:
        with sync_conn() as conn:
            row = conn.fetchone("SELECT focus, project, status, updated_at FROM active ORDER BY updated_at DESC LIMIT 1")
            return dict(row) if row else None
    except Exception as e:
        LOG.error("_get_active failed: %s", e, exc_info=True)
        return None


def _get_open_loops(limit: int = 5) -> list[dict]:
    try:
        with sync_conn() as conn:
            rows = conn.fetchall("SELECT content, project, priority FROM loops WHERE resolved = 0 ORDER BY priority DESC, created_at DESC LIMIT ?", (limit,))
            return rows
    except Exception as e:
        LOG.error("_get_open_loops failed: %s", e, exc_info=True)
        return []


def _get_knowledge(limit: int = 5) -> list[dict]:
    try:
        with sync_conn() as conn:
            rows = conn.fetchall("SELECT entity_type, name, description FROM knowledge WHERE archived = 0 ORDER BY id DESC LIMIT ?", (limit,))
            return rows
    except Exception as e:
        LOG.error("_get_knowledge failed: %s", e, exc_info=True)
        return []