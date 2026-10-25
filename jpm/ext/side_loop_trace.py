"""Per-loop LLM call tracing for the "side loops" that bypass the main
conversation-loop audit.

The main agent loop logs its LLM calls via ``_write_llm_audit_log`` /
``token_log`` in conversation_loop.py. But several *side* loops call the
LLM outside that path, so their request/response is invisible to the
audit:
  - self_impr  (jpm/ext/self_improvement.py:1137 ``_call_structured``)
  - JPM planner (jpm/core/_recall_planner.py via ``_call_refinement_llm``)
  - smart_refine (core/tools/_smart_refine.py:170 ``_call_refinement_llm``)
  - tool_flow_summarizer (core/agent/tool_flow_summarizer.py:287 ``_call_tool_flow_llm``)

This module writes ONE JSON file per turn per loop to
  $HERMES_HOME/logs/side_loops/<loop_name>/<YYYYMMDD_HHMMSS>_<turn>.json
with the request (what went in) and response (what came out). It is gated
by the SAME ``agent.token_log`` config flag as the compact token log, so it
flips on/off with that setting. The gate is read directly from config.yaml
(never from an agent object) so the planner, which has no agent, honours it.

Audit never breaks the loop: every write is best-effort inside try/except.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Cache the config path resolution + flag so we don't re-read YAML every call.
_cfg_home: Optional[Path] = None
_cfg_flag: Optional[bool] = None
_cfg_flag_ts: float = 0.0

SIDE_LOOPS_DIR = "logs/side_loops"


def _agent_home() -> Path:
    """Resolve the HOST agent's home dir (stock Hermes).

    Delegates to the engine's single host-home helper so the trace gate and the
    write path can never disagree about where the home is.
    """
    global _cfg_home
    if _cfg_home is not None:
        return _cfg_home
    try:
        from jpm.core._paths import _get_agent_home

        _cfg_home = Path(_get_agent_home())
    except Exception:
        _cfg_home = Path(os.path.expanduser("~")) / ".hermes"
    return _cfg_home


def side_loop_trace_enabled() -> bool:
    """True when the ``agent.token_log`` config flag is set.

    Reads the live config file (like ``_smart_refine._get_config``) so the
    gate follows the same knob the compact llm_audit.log uses — one toggle
    turns both on/off. Cached for a few seconds to avoid YAML re-reads on
    the hot path.
    """
    global _cfg_flag, _cfg_flag_ts
    now = time.time()
    if _cfg_flag is not None and (now - _cfg_flag_ts) < 5.0:
        return _cfg_flag
    try:
        import yaml
        path = _agent_home() / "config.yaml"
        if path.exists():
            with open(path) as _f:
                cfg = yaml.safe_load(_f) or {}
            agent_cfg = cfg.get("agent", {})
            _cfg_flag = bool(agent_cfg.get("token_log", False))
        else:
            _cfg_flag = False
    except Exception:
        _cfg_flag = False
    _cfg_flag_ts = now
    return _cfg_flag


def trace_side_loop(
    loop_name: str,
    *,
    turn_id: str = "",
    session_id: str = "",
    request: Optional[Dict[str, Any]] = None,
    response: Any = None,
    parsed: Any = None,
    duration_s: float = 0.0,
    attempts: int = 1,
    error: Optional[str] = None,
) -> None:
    """Write one per-loop, per-turn JSON trace file.

    Gated by the token_log config flag. Best-effort — a failed write never
    breaks the surrounding loop.
    """
    if not side_loop_trace_enabled():
        logger.debug("side_loop_trace: disabled for %s (token_log gate off)", loop_name)
        return
    #logger.info("side_loop_trace: writing %s trace (turn=%s) to %s", loop_name, turn_id, _agent_home() / SIDE_LOOPS_DIR / loop_name)
    try:
        loop_dir = _agent_home() / SIDE_LOOPS_DIR / loop_name
        loop_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # avoid clobbering when several traces land in the same second
        fname = f"{stamp}_{turn_id or 'na'}.json"
        path = loop_dir / fname
        # normalize response to a serializable form
        resp = response
        if hasattr(resp, "model_dump"):
            try:
                resp = resp.model_dump()
            except Exception:
                pass
        if hasattr(resp, "choices"):
            try:
                choice = getattr(resp, "choices", [None])[0] if getattr(resp, "choices", None) else None
                msg = getattr(choice, "message", None) if choice else None
                resp = {
                    "model": getattr(resp, "model", None),
                    "finish_reason": getattr(choice, "finish_reason", None) if choice else None,
                    "content": getattr(msg, "content", None) if msg else None,
                    "tool_calls": [
                        tc.function.name
                        for tc in (getattr(msg, "tool_calls", None) or [])
                    ] if msg and getattr(msg, "tool_calls", None) else None,
                }
            except Exception:
                pass
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "loop": loop_name,
            "turn": turn_id,
            "session": session_id,
            "duration_s": round(duration_s, 3),
            "attempts": attempts,
            "request_in": request or {},
            "response_out": resp if isinstance(resp, (dict, list, str, int, float, bool)) or resp is None
                             else repr(resp)[:2000],
            "parsed": parsed if isinstance(parsed, (dict, list, str, int, float, bool)) or parsed is None
                          else repr(parsed)[:2000],
            "error": error,
        }
        with open(path, "w") as f:
            json.dump(entry, f, indent=2, default=str)
    except Exception as e:  # pragma: no cover - audit must never break the loop
        logger.warning("side_loop_trace: write failed for %s (turn=%s): %s",
                       loop_name, turn_id, e)
        import traceback
        logger.warning("side_loop_trace: traceback:\n%s", traceback.format_exc())
