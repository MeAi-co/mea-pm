import os
import typing
from pathlib import Path
from typing import Any


def _get_joshaico_home() -> str:
    """Runtime data root — JOSHAICO_HOME is set by main.py at startup."""
    return os.environ.get("JOSHAICO_HOME", str(Path.home() / ".joshaico"))


# ARCHIVED 2026-08-15 — dead code audit: _paths._get_pg_config is shadowed by _pg._get_pg_config
# and never imported/called. Kept for reference per archive-don't-delete rule.
def _get_pg_config() -> typing.Optional[dict[str, Any]]:
    """Read PG connection config from env vars. Returns None if not configured."""
    host = os.environ.get("JPM_PG_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.environ.get("JPM_PG_PORT", "5432")),
        "database": os.environ.get("JPM_PG_DB", "jpm"),
        "user": os.environ.get("JPM_PG_USER", "postgres"),
        "password": os.environ.get("JPM_PG_PASSWORD", ""),
    }


def _get_yaml_path() -> str:
    return str(Path(_get_joshaico_home()) / "memory" / "JPM_MEMORY.yaml")
