import os
import typing
from pathlib import Path
from typing import Any


def _get_agent_home() -> str:
    """Resolve the HOST agent's runtime data root.

    mea_pm is a plugin for stock Hermes, so the host home is Hermes' home.
    Resolution order (first hit wins):

      1. ``HERMES_HOME`` env var — the stock contract, set by the launcher.
      2. ``hermes_constants.get_hermes_home()`` — stock's own resolver, which
         also honours a context-local override. Imported lazily and guarded so
         the engine still works when vendored outside a Hermes runtime.
      3. ``~/.hermes`` — stock's platform default.

    No other product's home variable is consulted: this engine ships inside
    mea_pm and resolves only the host agent's home.
    """
    env = os.environ.get("HERMES_HOME", "").strip()
    if env:
        return env

    try:
        from hermes_constants import get_hermes_home  # type: ignore

        return str(get_hermes_home())
    except Exception:
        pass

    return str(Path.home() / ".hermes")


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
    return str(Path(_get_agent_home()) / "memory" / "JPM_MEMORY.yaml")
