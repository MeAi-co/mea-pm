"""mea_skills — MEAI Skills (the ``skills_*`` tools).

Ports the Joshaico fork's skill toolset onto stock Hermes as a plugin:

  * ``skills_list``   — OVERRIDE of the stock tool (fork adds PG-backed catalog,
                        role tags, plugin-namespace dispatch).
  * ``skill_view``    — OVERRIDE (fork adds PG body fetch, section filter,
                        view/use telemetry bump).
  * ``skill_manage``  — OVERRIDE (fork adds PG dual-write, guard scan, write
                        approval gate).
  * ``skill_choose``  — NEW tool (no stock equivalent; ranked catalog +
                        section-level retrieval).

The three overrides need the operator grant
``plugins.entries.mea_skills.allow_tool_override: true`` in the profile
``config.yaml``. ``skill_choose`` is a pure addition and needs no grant.

Load order (verified in ``model_tools.py``): ``discover_builtin_tools()`` runs
first (line 149), then ``discover_plugins()`` (line 162). So the plugin
registers AFTER the built-ins and ``override=True`` genuinely replaces them.

The vendored tool modules carry fork-only imports (``joshaico_constants``,
``joshaico_cli.*``, ``tools.role_choose_tool``). ``_shims.install()`` aliases
those onto the stock modules BEFORE the vendored modules are imported, so the
fork sources run unmodified.

Stock loader contract (hermes_cli/plugins.py): discovery = a child dir with
``__init__.py`` + ``plugin.yaml`` under ``$HERMES_HOME/plugins/``; load = the
loader imports this package and calls ``register(ctx)``.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Make the vendored engine (``jpm``) and the vendored tool modules importable as
# top-level names. The loader imports THIS package under a synthetic name, so
# absolute self-imports need the plugin dir on sys.path.
#
# SINGLE OWNER: the engine lives in exactly ONE place — ``plugins/mea_pm/jpm/``.
# This plugin no longer vendors its own copy. Python caches a module in
# ``sys.modules`` under its bare name, so whichever plugin imports ``jpm``
# first binds that copy for the whole process; N copies meant the memory
# provider silently ran a DIFFERENT engine than the tool plugins. Point at the
# owner explicitly so load order cannot decide it.
_PLUGIN_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _PLUGIN_DIR.parent / "mea_pm"
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

import _shims  # noqa: E402

_shims.install()

from _skills_tool import (  # noqa: E402
    SKILLS_LIST_SCHEMA,
    SKILL_VIEW_SCHEMA,
    check_skills_requirements,
    skill_view,
    skills_list,
)
from _skill_manager_tool import SKILL_MANAGE_SCHEMA, skill_manage  # noqa: E402
from _skill_choose_tool import SKILL_CHOOSE_SCHEMA, skill_choose  # noqa: E402

logger = logging.getLogger(__name__)

__all__ = ["register"]

_TOOLSET = "skills"
_EMOJI_LIST = "\U0001f4da"    # 📚
_EMOJI_MANAGE = "\U0001f4dd"  # 📝


def _skills_list_handler(args: dict, **kw) -> str:
    args = args or {}
    return skills_list(category=args.get("category"), task_id=kw.get("task_id"))


def _skill_view_handler(args: dict, **kw) -> str:
    """Invoke skill_view, then bump view/use telemetry on success.

    Ported verbatim from the fork's ``_skill_view_with_bump``: under the
    brute-force directive model there is no skill-manager, so skill_view ==
    skill_load and every successful view bumps use_count too. Best-effort — a
    telemetry failure never breaks the tool call.
    """
    import json

    args = args or {}
    name = args.get("name", "")
    result = skill_view(
        name,
        file_path=args.get("file_path"),
        section=args.get("section"),
        task_id=kw.get("task_id"),
    )
    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict) and parsed.get("success"):
            resolved = parsed.get("name") or name
            if resolved:
                from tools.skill_usage import bump_use, bump_view
                bump_view(str(resolved))
                bump_use(str(resolved))
    except Exception:
        pass
    return result


def _skill_manage_handler(args: dict, **kw) -> str:
    args = args or {}
    return skill_manage(
        action=args.get("action", ""),
        name=args.get("name", ""),
        content=args.get("content"),
        category=args.get("category"),
        file_path=args.get("file_path"),
        file_content=args.get("file_content"),
        old_string=args.get("old_string"),
        new_string=args.get("new_string"),
        replace_all=args.get("replace_all", False),
        absorbed_into=args.get("absorbed_into"),
    )


def _skill_choose_handler(args: dict, **kw) -> str:
    args = args or {}
    return skill_choose(
        name=args.get("name"),
        names=args.get("names"),
        query=args.get("query"),
        sections=bool(args.get("sections")),
        load=args.get("load"),
        task_id=kw.get("task_id"),
    )


def register(ctx) -> None:
    """Stock plugin entry point: register the four skill tools."""
    # --- overrides (need allow_tool_override grant) --------------------------
    ctx.register_tool(
        name="skills_list",
        toolset=_TOOLSET,
        schema=SKILLS_LIST_SCHEMA,
        handler=_skills_list_handler,
        description=SKILLS_LIST_SCHEMA.get("description", ""),
        check_fn=check_skills_requirements,
        emoji=_EMOJI_LIST,
        override=True,
    )
    ctx.register_tool(
        name="skill_view",
        toolset=_TOOLSET,
        schema=SKILL_VIEW_SCHEMA,
        handler=_skill_view_handler,
        description=SKILL_VIEW_SCHEMA.get("description", ""),
        check_fn=check_skills_requirements,
        emoji=_EMOJI_LIST,
        override=True,
    )
    ctx.register_tool(
        name="skill_manage",
        toolset=_TOOLSET,
        schema=SKILL_MANAGE_SCHEMA,
        handler=_skill_manage_handler,
        description=SKILL_MANAGE_SCHEMA.get("description", ""),
        emoji=_EMOJI_MANAGE,
        override=True,
    )
    # --- pure addition (no grant needed) -------------------------------------
    ctx.register_tool(
        name="skill_choose",
        toolset=_TOOLSET,
        schema=SKILL_CHOOSE_SCHEMA,
        handler=_skill_choose_handler,
        description=SKILL_CHOOSE_SCHEMA.get("description", ""),
        check_fn=check_skills_requirements,
        emoji=_EMOJI_LIST,
    )
