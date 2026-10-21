"""jpm._ensure — schema ensure for JPM tables.

Ensures all core tables exist. PG schema is managed separately via
apply_schema() on the PG side.
"""
import logging

from ._pg import sync_conn, apply_schema

LOG = logging.getLogger(__name__)


def _ensure_db() -> None:
    """Ensure all core tables exist via PG schema.

    When PG is enabled, applies PG schema. Raises RuntimeError if PG
    is not configured — no SQLite fallback.
    """
    from ._pg import is_pg_enabled

    if is_pg_enabled():
        apply_schema()
        return

    raise RuntimeError(
        "_ensure_db: JPM_PG_HOST is not set or PG is unreachable. "
        "JPM requires PostgreSQL — no SQLite fallback available."
    )
