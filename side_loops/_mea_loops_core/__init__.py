"""_mea_loops_core — shared core for the MEAI per-loop plugins (P6).

This directory is **underscore-prefixed on purpose**: the stock plugin loader
skips ``_``/``.``-prefixed child dirs (``plugins/plugin_loader.py``
``iter_plugin_dirs``), so this is NOT discovered as a plugin. It is a shared
library that the per-loop plugins import.

Why it exists: the fork runs ALL turn-end loops sequentially inside ONE daemon
thread (``core/agent/turn_finalizer.py`` ``_run_background_review``), bounded by
a single watchdog budget. One wedged loop burns the budget and the watchdog
abandons the whole thread — every loop after it silently never runs. The fix is
one process per loop: a wedge kills only that loop.

This module provides the four pieces every per-loop plugin needs:

  * ``ShimAgent``      — the minimal agent surface the vendored engine reads.
  * ``launch_loop``    — spawn a DETACHED subprocess for one loop.
  * ``trace``          — write one per-loop, per-turn JSON trace file.
  * ``read_flag``      — read a loop's own ``enabled``/``interval`` config flag.

The subprocess entrypoint is ``python -m _mea_loops_core.run`` (see ``run.py``).

Fail-open everywhere: a loop failure never breaks a turn.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

LOG = logging.getLogger(__name__)

# ── Path resolution ─────────────────────────────────────────────────────────
# This file lives at <profile>/plugins/_mea_loops_core/__init__.py.
#   PLUGINS_DIR  = <profile>/plugins
#   PROFILE_HOME = <profile>
#   BASE_HOME    = the base hermes home (code tree + runtime interpreter)
PLUGINS_DIR = Path(__file__).resolve().parent.parent
PROFILE_HOME = PLUGINS_DIR.parent


def base_home() -> Path:
    """The base Hermes home (holds ``hermes-agent/`` and ``tools/``)."""
    return Path(os.environ.get("HERMES_BASE_HOME") or (Path.home() / ".hermes"))


def code_dir() -> Path:
    """The stock code tree (``hermes_cli/``, ``tools/``)."""
    return Path(os.environ.get("HERMES_CODE") or (base_home() / "hermes-agent"))


def runtime_python() -> str:
    """The interpreter the launcher execs for a loop subprocess.

    Prefer ``sys.executable`` — the hook fires INSIDE the gateway process, so
    that interpreter is guaranteed to carry every dependency the gateway itself
    has (httpx, asyncpg, the engine). A globbed ``tools/python-*`` path can
    resolve to a bare interpreter with an empty site-packages, which is exactly
    the failure this avoids. Fall back to the glob only when ``sys.executable``
    is unusable (e.g. a frozen/embedded build).
    """
    exe = sys.executable
    if exe and os.path.isfile(exe):
        return exe
    tools = base_home() / "tools"
    cands = sorted(tools.glob("python-*/bin/python3"))
    if cands:
        return str(cands[0])
    return exe or "python3"


def engine_dir() -> Path:
    """The vendored ``jpm`` engine — vendored ONCE under the sibling ``mea_pm``."""
    return PLUGINS_DIR / "mea_pm"


def side_loops_dir() -> Path:
    """Per-loop trace root: ``<profile>/logs/side_loops``."""
    return PROFILE_HOME / "logs" / "side_loops"


# ── Config reader ───────────────────────────────────────────────────────────
def read_flag(plugin_id: str, key: str, default: Any = None) -> Any:
    """Read ``plugins.entries.<plugin_id>.settings.<key>`` from the profile config.

    Read directly from ``config.yaml`` (never from an agent/ctx object) so the
    detached subprocess — which has no ``ctx`` — honours the same flag the
    in-process hook read. Best-effort: any error returns *default*.
    """
    try:
        import yaml
        path = PROFILE_HOME / "config.yaml"
        if not path.exists():
            return default
        with open(path, encoding="utf-8-sig") as f:
            cfg = yaml.safe_load(f) or {}
        entry = ((cfg.get("plugins") or {}).get("entries") or {}).get(plugin_id) or {}
        settings = entry.get("settings") or entry.get("config") or {}
        return settings.get(key, default)
    except Exception as exc:
        LOG.debug("_mea_loops_core: read_flag(%s.%s) failed: %s", plugin_id, key, exc)
        return default


def loop_enabled(plugin_id: str, default: bool = True) -> bool:
    """True when the loop's own ``enabled`` flag is set (default *default*)."""
    val = read_flag(plugin_id, "enabled", default)
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "on")
    return bool(val)


# ── Shim agent ──────────────────────────────────────────────────────────────
class ShimAgent:
    """Minimal agent surface the vendored self-improvement engine reads.

    The engine (``jpm.ext.self_improvement``) reads only: ``session_id``,
    ``model``/``base_url``/``api_key``, ``request_overrides``,
    ``_memory_nudge_interval``/``_skill_nudge_interval``,
    ``self_impr_min_new_messages``, and ``_create_openai_client(...)``.
    """

    def __init__(self, session_id: str, model: str = "", platform: str = "") -> None:
        self.session_id = session_id
        self.model = model
        self.platform = platform
        self.base_url = ""
        self.api_key = ""
        self.request_overrides: dict = {}
        self._memory_nudge_interval = 0
        self._skill_nudge_interval = 0
        self.self_impr_min_new_messages = 2
        # Truthiness sentinel ONLY. The vendored tool_flow_summarizer gates on
        # ``getattr(agent, "_session_db", None)`` but NEVER queries it — every
        # read/write goes through ``jpm.core._pg.sync_conn`` (PG). In the
        # detached subprocess there is no live agent, so the sentinel must be
        # truthy to mean "a session store is reachable" (it is: PG). Setting it
        # here is what lets toolflow run detached instead of no-op'ing.
        self._session_db = True

    def _create_openai_client(self, client_kwargs: dict, *, reason: str = "", shared: bool = False):
        """Delegate to stock's module-level client factory (no agent needed)."""
        from agent.auxiliary_client import _create_openai_client
        kwargs = dict(client_kwargs or {})
        api_key = kwargs.pop("api_key", None) or self.api_key
        base_url = kwargs.pop("base_url", None) or self.base_url
        return _create_openai_client(api_key=api_key, base_url=base_url, **kwargs)


def resolve_runtime() -> tuple[str, str, str]:
    """Best-effort ``(model, base_url, api_key)`` for the ACTIVE provider.

    Must go through stock's real resolver (``resolve_runtime_provider``), NOT
    the bare ``model:`` keys. A profile that names a provider
    (``model.provider: ollama-local``) keeps its endpoint under
    ``providers.<name>.api`` with a ``key_env`` pointer — there is no
    ``model.base_url`` / ``model.api_key`` at all, so reading those returns
    ``("", "", "")`` and every aux-LLM loop subprocess dies with an empty
    endpoint. The resolver walks the full ladder (named custom provider →
    local-endpoint bypass → pool → env) and returns the resolved
    ``provider/base_url/api_key/api_mode``.

    ``resolve_requested_provider`` normalises the configured provider name
    (e.g. ``ollama-local``) into the form the ladder expects. Falls back to
    ``requested=None`` (auto) when the config names nothing.
    """
    try:
        from hermes_cli.config import load_config
        from hermes_cli.runtime_provider import (
            resolve_runtime_provider,
            resolve_requested_provider,
        )
        cfg = load_config() or {}
        model_cfg = cfg.get("model", {}) or {}
        model = model_cfg.get("default") or ""
        try:
            requested = resolve_requested_provider(model_cfg.get("provider"))
        except Exception:
            requested = None
        rt = resolve_runtime_provider(
            requested=requested or None,
            target_model=model or None,
        ) or {}
        return (
            model,
            rt.get("base_url") or "",
            rt.get("api_key") or "",
        )
    except Exception:
        return "", "", ""


# ── Trace ───────────────────────────────────────────────────────────────────
def trace(loop_name: str, *, turn_id: str = "", session_id: str = "",
          duration_s: float = 0.0, result: Any = None,
          error: Optional[str] = None, extra: Optional[dict] = None) -> Optional[Path]:
    """Write one per-loop, per-turn JSON trace file. Best-effort, never raises."""
    try:
        loop_dir = side_loops_dir() / loop_name
        loop_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = loop_dir / f"{stamp}_{turn_id or 'na'}.json"
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "loop": loop_name,
            "turn": turn_id,
            "session": session_id,
            "duration_s": round(duration_s, 3),
            "result": result if isinstance(result, (dict, list, str, int, float, bool)) or result is None
                      else repr(result)[:2000],
            "error": error,
        }
        if extra:
            entry.update(extra)
        with open(path, "w") as f:
            json.dump(entry, f, indent=2, default=str)
        return path
    except Exception as exc:  # pragma: no cover — audit must never break the loop
        LOG.warning("_mea_loops_core: trace write failed for %s: %s", loop_name, exc)
        return None


# ── Detached-subprocess launcher ────────────────────────────────────────────
def launch_loop(loop_name: str, *, session_id: str, turn_id: str = "",
                payload: Optional[dict] = None, timeout_s: float = 0.0) -> Optional[int]:
    """Spawn a DETACHED subprocess to run one loop. Returns the PID (or None).

    The subprocess re-enters the vendored engine with a shim agent and writes a
    trace. Detached (``start_new_session=True``) so a wedge in one loop cannot
    starve the others — the whole point of the per-loop-process redesign.

    The payload (conversation snapshot etc.) is written to a temp JSON file and
    passed by path, avoiding stdin size limits.
    """
    try:
        import tempfile
        payload_path = ""
        if payload is not None:
            fd, payload_path = tempfile.mkstemp(prefix=f"mea_loop_{loop_name}_", suffix=".json")
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, default=str)

        env = dict(os.environ)
        env["HERMES_HOME"] = str(PROFILE_HOME)
        # Make the stock tree + core + engine importable in the child.
        parts = [str(code_dir()), str(PLUGINS_DIR), str(engine_dir())]
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(parts + ([existing] if existing else []))

        cmd = [
            runtime_python(), "-m", "_mea_loops_core.run",
            "--loop", loop_name,
            "--session", session_id or "",
            "--turn", turn_id or "",
            "--payload", payload_path,
        ]
        proc = subprocess.Popen(
            cmd, env=env, cwd=str(PROFILE_HOME),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # detached: survives the parent, isolated
        )
        LOG.info("_mea_loops_core: launched loop %s pid=%s", loop_name, proc.pid)
        return proc.pid
    except Exception as exc:
        LOG.warning("_mea_loops_core: launch_loop(%s) failed: %s", loop_name, exc)
        return None


__all__ = [
    "ShimAgent", "launch_loop", "trace", "read_flag", "loop_enabled",
    "resolve_runtime", "runtime_python", "code_dir", "engine_dir",
    "side_loops_dir", "PLUGINS_DIR", "PROFILE_HOME",
]
