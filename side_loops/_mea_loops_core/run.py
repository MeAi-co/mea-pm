"""_mea_loops_core.run — detached-subprocess entrypoint for one MEAI loop.

Invoked as::

    python -m _mea_loops_core.run --loop <name> --session <id> --turn <id> --payload <path>

Runs ONE loop in its own process (so a wedge kills only this loop), then writes
a per-loop trace and exits. Fail-open: any error is traced and the process exits
0 so the parent never sees a spurious failure.

Loop dispatch table maps a loop name to a callable ``fn(shim, payload) -> result``.
The heavy engine imports happen INSIDE the dispatch (lazy) so a missing engine
degrades to a traced error rather than an import crash at module load.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Ensure the core package + engine are importable when run as ``-m``.
_HERE = Path(__file__).resolve().parent
_PLUGINS = _HERE.parent
for _d in (_PLUGINS, _PLUGINS / "mea_pm"):
    if _d.is_dir() and str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOG = logging.getLogger("_mea_loops_core.run")


# ── Loop implementations ────────────────────────────────────────────────────
def _loop_state_sync(shim, payload: dict):
    """Turn-end state sync (pulse/active/loops). Every turn end."""
    from jpm.ext.self_improvement import run_state_sync
    messages = payload.get("messages") or []
    writes = run_state_sync(shim, messages, gap_ids=payload.get("gap_ids"))
    return {"writes": writes}


def _loop_self_impr(shim, payload: dict):
    """Self-improvement (user understanding + agent growth). Nudge boundary."""
    from jpm.ext.self_improvement import run_self_improvement
    messages = payload.get("messages") or []
    out = run_self_improvement(
        shim, messages_snapshot=messages,
        review_memory=bool(payload.get("review_memory", True)),
        review_skills=bool(payload.get("review_skills", True)),
        sync_state=False,
        gap_ids=payload.get("gap_ids"),
    )
    return {"tuple": list(out) if isinstance(out, (tuple, list)) else out}


def _loop_agent_digest(shim, payload: dict):
    """Agent-message digest compressor (in-place per-row UPDATE). Turn end.

    Uses the VENDORED copy (``_mea_loops_core/vendor/agent_digest.py``) — the
    module is fork-specific (stock has no ``agent.agent_digest``), so it must
    not depend on the live fork tree.
    """
    from _mea_loops_core.vendor.agent_digest import run_agent_digest
    n = run_agent_digest(shim, current_turn_id=payload.get("current_turn_id"))
    return {"digested": n}


def _loop_anchor(shim, payload: dict):
    """Volatile session anchor (DB-only generation). Nudge boundary.

    Reads the lean surviving trajectory from the DB, condenses it to 1-3
    first-person sentences via the aux LLM, and persists it to the anchor
    store. The INJECTION half is in-process (llm_request middleware) — a
    subprocess cannot mutate the parent's request.
    """
    from _mea_loops_core import anchor_store
    from _mea_loops_core.vendor.agent_anchor import build_anchor
    session_id = shim.session_id
    anchor = build_anchor(shim, session_id)
    if not anchor:
        return {"anchor": None}
    ok = anchor_store.set_anchor(session_id, anchor)
    return {"anchor": anchor, "persisted": ok}


def _loop_toolflow(shim, payload: dict):
    """Tool-flow summarizer (DB-only). Turn end, api_call_count >= 2.

    Collapses the verbose tool-call wall between the last two stop boundaries
    into a deterministic one-line-per-tool summary. The vendored copy is
    DB-only: it reads/writes ``messages`` via ``jpm.core._pg.sync_conn`` and
    touches the agent ONLY through ``getattr`` for ``session_id`` — so it runs
    cleanly in a detached subprocess. The in-memory ``_collapse_in_memory``
    mirror is a no-op here (the subprocess has no live message list); the DB
    UPDATE is what the next turn re-reads.
    """
    from _mea_loops_core.vendor.tool_flow_summarizer import summarize_tool_flow
    freeze = payload.get("turn_freeze_ts")
    turn_freeze_ts = None
    if freeze:
        try:
            from datetime import datetime
            turn_freeze_ts = datetime.fromisoformat(freeze)
        except Exception:
            turn_freeze_ts = None
    collapsed, gap_ids = summarize_tool_flow(shim, [], turn_freeze_ts=turn_freeze_ts)
    return {"collapsed": collapsed, "gap_ids": list(gap_ids or [])}


def _loop_recompact(shim, payload: dict):
    """Tier-2 session-summary recompact (DB-only). Nudge boundary.

    Condenses uncompacted ``session_summary_log`` rows (+ the volatile anchor,
    read from the anchor store) into ONE first-person ``sessions.summary``
    brief, then flips the absorbed rows. Runs right AFTER the anchor so the
    fresh anchor feeds in as a source. DB-only → detached.
    """
    from _mea_loops_core import anchor_store
    from _mea_loops_core.vendor.agent_anchor import recompact_session_summary
    anchor = anchor_store.get_anchor(shim.session_id)
    brief = recompact_session_summary(shim, anchor=anchor)
    return {"brief_chars": len(brief) if brief else 0}


_LOOPS = {
    "state_sync": _loop_state_sync,
    "self_impr": _loop_self_impr,
    "agent_digest": _loop_agent_digest,
    "anchor": _loop_anchor,
    "toolflow": _loop_toolflow,
    "recompact": _loop_recompact,
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="_mea_loops_core.run")
    ap.add_argument("--loop", required=True)
    ap.add_argument("--session", default="")
    ap.add_argument("--turn", default="")
    ap.add_argument("--payload", default="")
    args = ap.parse_args(argv)

    from _mea_loops_core import ShimAgent, resolve_runtime, trace

    payload: dict = {}
    if args.payload:
        try:
            with open(args.payload) as f:
                payload = json.load(f) or {}
        except Exception as exc:
            LOG.warning("payload read failed: %s", exc)

    fn = _LOOPS.get(args.loop)
    if fn is None:
        trace(args.loop, turn_id=args.turn, session_id=args.session,
              error=f"unknown loop {args.loop!r}")
        return 0

    model, base_url, api_key = resolve_runtime()
    shim = ShimAgent(args.session, model=model, platform=payload.get("platform", ""))
    shim.base_url = base_url
    shim.api_key = api_key

    t0 = time.monotonic()
    try:
        result = fn(shim, payload)
        trace(args.loop, turn_id=args.turn, session_id=args.session,
              duration_s=time.monotonic() - t0, result=result)
        LOG.info("loop %s done in %.2fs: %s", args.loop, time.monotonic() - t0, result)
    except Exception as exc:
        import traceback
        trace(args.loop, turn_id=args.turn, session_id=args.session,
              duration_s=time.monotonic() - t0, error=f"{exc}",
              extra={"traceback": traceback.format_exc()[-2000:]})
        LOG.warning("loop %s failed (fail-open): %s", args.loop, exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
