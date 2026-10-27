"""mea_messages — MEAI Messages (the ``messages`` tool).

Exposes the vendored ``jpm`` engine's message-level recall as a bare
``messages`` tool. The engine lives untouched in ``./jpm/`` (vendored from the
Joshaico fork) so its absolute ``from jpm.core...`` self-imports resolve.

Stock loader contract (hermes_cli/plugins.py):
  * discovery: a child dir with ``__init__.py`` + ``plugin.yaml`` under
    ``$HERMES_HOME/plugins/``.
  * load: the loader imports this package and calls ``register(ctx)``.
  * ``ctx.register_tool(name, toolset, schema, handler, emoji=...)`` adds the
    tool to the global registry. The registered ``name`` IS the model-facing
    function name — so we register ``messages`` (bare), never ``mea_messages``.

Stock has NO ``messages`` tool (verified: only ``session_search`` exists), so
this is a PURE ADDITION — no ``override=True`` and no operator grant needed.

Display: the progress bubble renders the raw tool name when no curated verb
exists, so registering as ``messages`` yields ``💬 messages: "…"`` for free.
The emoji is forwarded via ``register_tool(emoji=...)``.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the vendored engine importable as top-level ``jpm``. The loader imports
# THIS package under a synthetic name, so the engine's absolute ``jpm.*``
# self-imports need ``jpm`` resolvable on sys.path.
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

from _messages_tool import MESSAGES_SCHEMA, messages  # noqa: E402

__all__ = ["register"]

_TOOL_NAME = "messages"
_TOOLSET = "session_search"
_EMOJI = "\U0001f4ac"  # 💬

# Stock has no `messages` tool, so no stock guidance mentions it. Register a
# bounded section so the agent knows message-level search exists alongside
# `sessions` (which covers session-level recall).
_MESSAGES_GUIDANCE = (
    "`messages` — EXACT-MESSAGE / cross-session sweep: searches individual "
    "messages across ALL sessions. Use it to find one specific message or get "
    "situational awareness — pass a query to search, or no query to browse "
    "recent messages.\n"
    "Search order: HYBRID — full-text runs first, then pgvector semantic recall "
    "is RRF-merged in, so paraphrased and non-exact queries still surface hits. "
    "A keyword miss is NOT evidence of absence; try a paraphrase before "
    "concluding nothing exists.\n"
    "For durable facts use `vault`; for session-level recall use `sessions`."
)


def _messages_handler(args: dict, **kwargs) -> str:
    """Route a ``messages`` call into the vendored tool function."""
    args = args or {}
    return messages(
        query=args.get("query") or "",
        role=args.get("role"),
        filter=args.get("filter", "messages"),
        limit=args.get("limit", 20),
        offset=args.get("offset", 0),
        smart=args.get("smart", False),
        current_session_id=kwargs.get("session_id"),
    )


def register(ctx) -> None:
    """Stock plugin entry point: register the bare ``messages`` tool."""
    ctx.register_tool(
        name=_TOOL_NAME,
        toolset=_TOOLSET,
        schema=MESSAGES_SCHEMA,
        handler=_messages_handler,
        description=MESSAGES_SCHEMA.get("description", ""),
        emoji=_EMOJI,
    )
    # Tell the agent the tool exists (stock has no guidance for it).
    try:
        ctx.register_system_prompt_section(
            "mea.messages", _MESSAGES_GUIDANCE, position="after_memory", max_chars=800,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("mea_messages: could not register guidance section: %s", e)
