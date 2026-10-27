"""mea-warmstart — warm replay / warm start for a cold agent.

The gap this closes: on ``/new``, ``/reset``, or a gateway reboot the agent wakes up
blank. Postgres is the replay source (it mirrors every session and survives a state.db
rewrite); only user turns and their final answers are replayed, never tool chatter.
Nothing is written to any store.

Seam: ``llm_request`` middleware. A cold session is detected structurally (the
request carries at most one non-system message), so no session-start hook is needed —
stock does not expose one to plugins.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from . import _replay

LOG = logging.getLogger(__name__)

PLUGIN_ID = "mea-warmstart"
PROFILE_HOME = Path.home() / ".hermes"
LOADED_AT = time.time()          # gateway boot marker
_PRIMED: set[str] = set()        # sessions already primed this process


def _settings() -> dict[str, Any]:
    """``plugins.entries.<id>.settings`` from the profile config, best-effort."""
    try:
        import yaml

        path = PROFILE_HOME / "config.yaml"
        if not path.exists():
            return {}
        with open(path, encoding="utf-8-sig") as f:
            cfg = yaml.safe_load(f) or {}
        entry = ((cfg.get("plugins") or {}).get("entries") or {}).get(PLUGIN_ID) or {}
        return dict(entry.get("settings") or entry.get("config") or {})
    except Exception as exc:
        LOG.debug("mea-warmstart: settings read failed: %s", exc)
        return {}


def _flag(cfg: dict[str, Any], key: str, default: Any) -> Any:
    val = cfg.get(key, default)
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "on")
    return bool(val) if isinstance(default, bool) else val


def _is_cold(messages: list[dict[str, Any]]) -> bool:
    """True when the request has no conversation of its own yet."""
    convo = [m for m in messages if isinstance(m, dict) and m.get("role") != "system"]
    return len(convo) <= 1


def _rewrite(request: Any = None, **ctx: Any) -> dict[str, Any] | None:
    """``llm_request`` middleware: inject the warm block on a cold start."""
    try:
        if not isinstance(request, dict):
            return None
        messages = request.get("messages")
        if not isinstance(messages, list) or not messages:
            return None
        if not _is_cold(messages):
            return None

        session_id = str(ctx.get("session_id") or "")
        if not session_id or session_id in _PRIMED:
            return None

        cfg = {**_replay.DEFAULTS, **_settings()}
        if not _flag(cfg, "enabled", True):
            return None

        boot_window = float(cfg.get("boot_window_seconds", 900) or 0)
        boot_recent = (time.time() - LOADED_AT) <= boot_window
        if boot_recent:
            if not _flag(cfg, "on_boot", True):
                return None
            header = "## Warm start (gateway reboot)"
        else:
            if not _flag(cfg, "on_cold_start", True):
                return None
            header = "## Warm replay"

        block, reason = _replay.build(
            current_session_id=session_id,
            source=str(ctx.get("platform") or ""),
            settings=cfg,
        )
        if not block:
            LOG.info("mea-warmstart: no replay for %s (%s)", session_id, reason)
            _PRIMED.add(session_id)
            return None

        block = block.replace("## Warm replay", header, 1)

        insert_at = 1 if messages and messages[0].get("role") == "system" else 0
        new_messages = list(messages)
        new_messages.insert(insert_at, {"role": "system", "content": block})
        _PRIMED.add(session_id)

        LOG.info(
            "mea-warmstart: primed %s (%s, %d chars, header=%s)",
            session_id, reason, len(block), header,
        )
        out = dict(request)
        out["messages"] = new_messages
        return {"request": out, "source": PLUGIN_ID, "reason": reason}
    except Exception as exc:  # fail-open: never block a turn
        LOG.warning("mea-warmstart: middleware failed (ignored): %s", exc)
        return None


def register(ctx) -> None:
    """Stock plugin entry point."""
    ctx.register_middleware("llm_request", _rewrite)
