"""mea_vault — MEAI Vault (the ``vault`` tool).

Exposes the vendored ``jpm`` engine's unified dispatcher as a bare ``vault``
tool. The engine lives untouched in ``./jpm/`` (vendored from the Joshaico
fork) so its absolute ``from jpm.core...`` self-imports resolve.

Stock loader contract (hermes_cli/plugins.py):
  * discovery: a child dir with ``__init__.py`` + ``plugin.yaml`` under
    ``$HERMES_HOME/plugins/``.
  * load: the loader imports this package and calls ``register(ctx)``.
  * ``ctx.register_tool(name, toolset, schema, handler, emoji=...)`` adds the
    tool to the global registry. The registered ``name`` IS the model-facing
    function name — so we register ``vault`` (bare), never ``mea_vault``.

Display: the progress bubble renders the raw tool name when no curated verb
exists, so registering as ``vault`` yields ``🤖 vault: "…"`` for free. The
emoji is forwarded via ``register_tool(emoji=...)``.
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

from jpm.core._provider import JPMemoryProvider  # noqa: E402
from jpm.core._schemas import JPM_SCHEMA  # noqa: E402

__all__ = ["register"]

# The engine's dispatcher keys on the tool name "jpm"; we register the tool as
# "vault" but route into the same handler.
_ENGINE_TOOL = "jpm"
_TOOL_NAME = "vault"
_TOOLSET = "vault"
_EMOJI = "\U0001f916"  # 🤖

# One engine instance for the process; the tool is stateless across calls
# (each call opens its own PG connection via the engine's sync_conn()).
_provider: JPMemoryProvider | None = None


def _get_provider() -> JPMemoryProvider:
    global _provider
    if _provider is None:
        _provider = JPMemoryProvider()
        _provider.initialize("vault-tool")
    return _provider


def _vault_handler(args: dict, **kwargs) -> str:
    """Route a ``vault`` call into the engine's unified dispatcher."""
    return _get_provider().handle_tool_call(_ENGINE_TOOL, args or {})


def _vault_schema() -> dict:
    """The engine schema with the tool name rewritten to ``vault``."""
    schema = dict(JPM_SCHEMA)
    schema["name"] = _TOOL_NAME
    return schema


# Stock has no `vault` tool, so no stock guidance mentions it. Register a
# bounded section so the agent knows the durable-fact store exists and how it
# relates to the two recall tools (`sessions`, `messages`). Without this the
# agent never reaches for `vault` and re-derives facts it already stored.
_VAULT_GUIDANCE = (
    "`vault` — DURABLE FACTS: user preferences, rules, identity, project "
    "knowledge, decisions. Use it to recall what is KNOWN (not what was said). "
    "Search it before asking the user to repeat a preference or re-deriving a "
    "decision. Actions: search, fetch, probe, get, list.\n"
    "Search order: VECTOR-FIRST (pgvector + Ollama embeddings), so paraphrased "
    "and non-exact queries work. FTS5 full-text is only a fallback when "
    "embeddings are unavailable. A keyword miss is NOT evidence of absence — "
    "top-k recall cannot establish absence.\n"
    "For conversation recall use `sessions`; for one specific message use "
    "`messages`."
)


def register(ctx) -> None:
    """Stock plugin entry point: register the bare ``vault`` tool."""
    schema = _vault_schema()
    ctx.register_tool(
        name=_TOOL_NAME,
        toolset=_TOOLSET,
        schema=schema,
        handler=_vault_handler,
        description=schema.get("description", ""),
        emoji=_EMOJI,
    )
    # Tell the agent the durable-fact store exists and how it routes against
    # the two recall tools. Bounded section (after_memory), rendered once per
    # session, persisted by core.
    try:
        ctx.register_system_prompt_section(
            "mea.vault", _VAULT_GUIDANCE, position="after_memory", max_chars=1000,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("mea_vault: could not register guidance section: %s", e)
