"""mea_sessions — MEAI Sessions (the ``sessions`` tool).

A fork of the Joshaico fork's ``session_search`` tool, retargeted at the MEAI
PostgreSQL memory interface: FTS over ``messages.search_vector`` plus a pgvector
semantic-recall fallback, deduped by session lineage, ranked newest-first.

Two things happen in ``register(ctx)``:

  1. Register the bare ``sessions`` tool (new name — no collision with stock).
  2. DISABLE the stock ``session_search``:
       a. ``registry.deregister("session_search")`` — removes it from the model's
          advertised tool list (``get_definitions`` skips names with no entry).
          NOTE: ``session_search`` is an AGENT-LOOP tool, not a registry tool, so
          ``registry.get_entry("session_search")`` is None and this call is a
          guarded no-op. It is kept for the case where a future stock build does
          register it. No operator grant is needed for this path.
       b. Rebind ``INLINE_TOOL_EXECUTORS["session_search"]`` to the new
          implementation, so any legacy caller that still names the old tool
          routes to MEAI instead of the stock SQLite path. This is the step that
          actually disables the stock tool, and it is NOT grant-gated.

Both are runtime operations from the plugin — the stock tree on disk is never
touched, so ``git pull`` / auto-update cannot clobber them.

Stock loader contract (hermes_cli/plugins.py): discovery = a child dir with
``__init__.py`` + ``plugin.yaml`` under ``$HERMES_HOME/plugins/``; load = the
loader imports this package and calls ``register(ctx)``.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Make the vendored engine importable as top-level ``jpm`` (absolute self-imports).
#
# SINGLE OWNER: the engine lives in exactly ONE place — ``plugins/mea_pm/jpm/``.
# This plugin no longer vendors its own copy. Python caches a module in
# ``sys.modules`` under its bare name, so whichever plugin imports ``jpm``
# first binds that copy for the whole process; N copies meant the memory
# provider silently ran a DIFFERENT engine than the tool plugins. Point at the
# owner explicitly so load order cannot decide it.
_PLUGIN_DIR = Path(__file__).resolve().parent


def _find_engine_dir() -> Path:
    """Locate the single ``jpm`` engine, wherever this plugin is installed.

    Two layouts must both work:
      * installed siblings — ``plugins/mea_pm/`` and ``plugins/mea_sessions/``
      * monorepo           — ``mea_pm/side_loops/mea_sessions/``
    Walk up from this file and take the first ancestor that actually contains
    ``jpm/core/_provider.py``. No hardcoded depth, no hardcoded path.
    """
    # Two layouts: installed siblings (plugins/<plugin> next to plugins/mea_pm)
    # and monorepo (mea_pm/side_loops/<plugin> under mea_pm). Check each ancestor
    # for the engine in place, then for a sibling mea_pm/ before walking further.
    for parent in _PLUGIN_DIR.parents:
        for candidate in (parent, parent / "mea_pm"):
            if (candidate / "jpm" / "core" / "_provider.py").is_file():
                return candidate
    raise ImportError(
        f"mea engine (jpm/core/_provider.py) not found above {_PLUGIN_DIR}. "
        "Install mea_pm alongside this plugin, or run from the mea_pm repo."
    )


_ENGINE_DIR = _find_engine_dir()
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from _sessions_tool import SESSIONS_SCHEMA, sessions  # noqa: E402
from _mirror import on_post_llm_call  # noqa: E402

logger = logging.getLogger(__name__)

__all__ = ["register"]

_TOOL_NAME = "sessions"
_TOOLSET = "session_search"   # group under the existing recall toolset
_EMOJI = "\U0001f50e"          # 🔎
_LEGACY_NAME = "session_search"


def _sessions_handler(args: dict, **kwargs) -> str:
    """Route a ``sessions`` call into the vendored tool function."""
    args = args or {}
    return sessions(
        query=args.get("query") or "",
        role_filter=args.get("role_filter"),
        limit=args.get("limit", 3),
        session_id=args.get("session_id"),
        around_message_id=args.get("around_message_id"),
        window=args.get("window", 5),
        sort=args.get("sort"),
        profile=args.get("profile"),
        detail=args.get("detail", "adaptive"),
        current_session_id=kwargs.get("session_id"),
    )


_DISABLED_SCHEMA = {
    "name": _LEGACY_NAME,
    "description": "Disabled. Use the `sessions` tool instead.",
    "parameters": {"type": "object", "properties": {}},
}

# Stock renders SESSION_SEARCH_GUIDANCE only when "session_search" is in
# valid_tool_names (agent/system_prompt.py). We hide that tool, so the stock
# guidance is suppressed and the replacement `sessions` tool would ship with
# NO instruction to reach for it. This bounded section restores it.
_SESSIONS_GUIDANCE = (
    "`sessions` — SESSION-LEVEL recall: what was said in a past conversation. "
    "Use for 'where did we leave X'. Returns matching messages with session id "
    "and timestamps.\n"
    "Search order: HYBRID — full-text runs first, then pgvector semantic recall "
    "is merged in when full-text returns thin results, so paraphrased and "
    "non-exact queries still surface hits. A keyword miss is NOT evidence of "
    "absence; try a paraphrase before concluding nothing exists.\n"
    "Do not ask the user to repeat themselves when `sessions` can find it. "
    "For durable facts use `vault`; for one specific message use `messages`."
)


def _disabled_handler(args: dict, **kwargs) -> str:
    return "session_search is disabled; use the `sessions` tool."


def _disable_legacy_session_search(ctx) -> None:
    """Hide stock ``session_search`` from the advertised surface and route any
    legacy call to MEAI. Best-effort: a failure here must not stop the new
    ``sessions`` tool from registering.

    A scoped plugin CANNOT deregister a process-global tool: ``registry.deregister``
    raises ``PermissionError`` ("Scoped plugin module ... cannot deregister
    process-global tool ...; register a scoped override instead"). The sanctioned
    path is a scoped override — register a same-named entry in the profile overlay
    whose ``check_fn`` returns False, so ``get_definitions`` skips it. The global
    entry is shadowed in the merged view and never advertised.
    """
    # (a) Shadow the global entry with a hidden scoped override.
    try:
        # Force the stock module to import first so its module-level
        # registry.register() has run and the shadow relationship is explicit.
        try:
            import tools.session_search_tool  # noqa: F401
        except Exception:
            pass
        ctx.register_tool(
            name=_LEGACY_NAME,
            toolset=_LEGACY_NAME,
            schema=_DISABLED_SCHEMA,
            handler=_disabled_handler,
            check_fn=lambda: False,
            override=True,
        )
        logger.info("mea_sessions: hid legacy tool %r via scoped override", _LEGACY_NAME)
    except Exception as e:
        logger.warning("mea_sessions: could not hide %r: %s", _LEGACY_NAME, e)

    # (b) Rebind the agent-loop inline executor so legacy calls route to MEAI.
    try:
        from agent import inline_tool_executors as _ite

        def _legacy_exec(agent, args, _ctx):  # noqa: ANN001
            return _sessions_handler(args or {}, session_id=getattr(agent, "session_id", None))

        _ite.INLINE_TOOL_EXECUTORS[_LEGACY_NAME] = _legacy_exec
        logger.info("mea_sessions: rebound inline executor %r -> MEAI", _LEGACY_NAME)
    except Exception as e:
        logger.warning("mea_sessions: could not rebind %r: %s", _LEGACY_NAME, e)


def register(ctx) -> None:
    """Stock plugin entry point."""
    ctx.register_tool(
        name=_TOOL_NAME,
        toolset=_TOOLSET,
        schema=SESSIONS_SCHEMA,
        handler=_sessions_handler,
        description=SESSIONS_SCHEMA.get("description", ""),
        emoji=_EMOJI,
    )
    _disable_legacy_session_search(ctx)
    # Restore the recall guidance stock suppresses when it hides session_search.
    # Bounded section (after_memory), rendered once per session, persisted by core.
    try:
        ctx.register_system_prompt_section(
            "mea.sessions", _SESSIONS_GUIDANCE, position="after_memory", max_chars=1200,
        )
        logger.info("mea_sessions: registered system prompt section mea.sessions")
    except Exception as e:
        logger.warning("mea_sessions: could not register guidance section: %s", e)
    # Mirror every persisted turn from SQLite state.db into PG so this tool
    # (and mea_messages) see the agent's OWN live conversation, not just seed
    # data. Plugin-only: a post_llm_call hook, no core edit.
    ctx.register_hook("post_llm_call", on_post_llm_call)
