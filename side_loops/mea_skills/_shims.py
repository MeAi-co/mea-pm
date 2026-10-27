"""Shim layer for the vendored MEAI skill tools.

The three vendored tool modules (``_skills_tool``, ``_skill_manager_tool``,
``_skill_choose_tool``) were lifted from the Joshaico fork and carry fork-only
imports that do not exist in stock Hermes:

  * ``joshaico_constants``      -> stock ``hermes_constants``
  * ``joshaico_cli.config``     -> stock ``hermes_cli.config``
  * ``joshaico_cli.plugins``    -> stock ``hermes_cli.plugins``
  * ``tools.role_choose_tool``  -> absent in stock (roles are a fork feature)

Rather than edit the vendored sources (which would drift from the fork), we
install thin alias modules into ``sys.modules`` BEFORE the vendored tools are
imported. Each alias re-exports the stock symbol under the fork's name, so the
vendored code runs unmodified.

``install()`` is idempotent and must be called before importing the vendored
tool modules.
"""
from __future__ import annotations

import sys
import types

_INSTALLED = False


def _alias(name: str, **attrs) -> types.ModuleType:
    """Create (or fetch) a module named ``name`` and attach ``attrs``."""
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def install() -> None:
    """Install the fork->stock alias modules. Idempotent."""
    global _INSTALLED
    if _INSTALLED:
        return

    # --- joshaico_constants -> hermes_constants -------------------------------
    import hermes_constants as _hc

    def _load_role_bundles() -> dict:
        """Roles are a fork feature; stock has no role bundles. Return {} so the
        vendored code's role-footer path degrades to 'no role set'."""
        return {}

    _alias(
        "joshaico_constants",
        get_joshaico_home=_hc.get_hermes_home,
        display_joshaico_home=_hc.display_hermes_home,
        get_default_joshaico_root=_hc.get_default_hermes_root,
        load_role_bundles=_load_role_bundles,
    )

    # --- joshaico_cli.config -> hermes_cli.config -----------------------------
    import hermes_cli.config as _hcfg

    _alias("joshaico_cli", __path__=[])  # namespace package placeholder
    _alias(
        "joshaico_cli.config",
        cfg_get=_hcfg.cfg_get,
        load_config=_hcfg.load_config,
    )

    # --- joshaico_cli.plugins -> hermes_cli.plugins ---------------------------
    import hermes_cli.plugins as _hp

    _alias(
        "joshaico_cli.plugins",
        _get_disabled_plugins=_hp._get_disabled_plugins,
        get_plugin_manager=_hp.get_plugin_manager,
        discover_plugins=_hp.discover_plugins,
    )

    # --- tools.role_choose_tool -> stub (absent in stock) ---------------------
    # The vendored skills_tool lazily imports ``_current_role`` inside a
    # try/except that returns None on failure, so a stub is sufficient.
    import tools  # ensure the package is imported first

    def _current_role():
        return None

    _alias("tools.role_choose_tool", _current_role=_current_role)

    _INSTALLED = True
