"""Which profile a memory read or write belongs to.

A single PG store can serve several Hermes profiles at once. The stores differ in
how they are scoped, and the split is deliberate:

* ``knowledge`` is scoped per profile. Facts and rules learned by one agent are
  that agent's, so another profile's recall must not surface them.
* ``entities`` stays shared. A person is the same person in every profile, and
  splitting the graph would fragment identity for no benefit. Reads that walk the
  graph still filter the facts they pull back through the profile scope.
* ``reflections`` carry a ``session_id``; their scope is inherited from the
  session, which records its own profile.

Resolution order matches core (``hermes_cli.profiles.current_profile_name``): the
profile home resolved by core, which is override-aware and therefore correct on a
multiplexed gateway whose process belongs to a different profile than the turn.
The environment is only consulted when that lookup is unavailable, because
``os.environ`` describes the LAUNCH profile and would mislabel a routed turn.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

LOG = logging.getLogger("jpm.profile")

DEFAULT_PROFILE = "default"
SCOPE_ENV = "JPM_KNOWLEDGE_SCOPE"


def name_from_home(home) -> str | None:
    """Profile name encoded in a Hermes home path, else None.

    A named profile lives at ``<root>/profiles/<name>``; the default profile IS
    the root home, which sits directly under the user's home directory. Anything
    deeper or shallower than those two shapes yields None: guessing here would
    mislabel rows, and a wrong label is worse than an absent one.
    """
    if not home:
        return None
    try:
        path = Path(str(home)).expanduser()
    except (TypeError, ValueError):
        return None
    if path.name == "profiles":
        return None
    if path.parent.name == "profiles":
        return path.name or None
    if path.parent.name and path.name not in ("", ".hermes"):
        return DEFAULT_PROFILE
    if path.name == ".hermes":
        return DEFAULT_PROFILE
    return None


def _live_home() -> str | None:
    try:
        from hermes_constants import get_hermes_home  # type: ignore

        return str(get_hermes_home())
    except Exception:
        return None


def current_profile() -> str:
    """Profile that owns the work happening right now.

    Never cached: one long-lived gateway process can serve several profiles, so a
    cached answer would attribute a routed turn to the wrong one.
    """
    name = name_from_home(_live_home())
    if name:
        return name
    for env_name in ("HERMES_PROFILE_NAME", "HERMES_PROFILE"):
        value = (os.environ.get(env_name) or "").strip()
        if value:
            return value
    return DEFAULT_PROFILE


def scope_mode() -> str:
    """How widely knowledge reads are allowed to look: ``own`` (default) or ``all``."""
    value = (os.environ.get(SCOPE_ENV) or "own").strip().lower()
    return value if value in ("own", "all") else "own"


def knowledge_scope(alias: str = "", include_all: bool | None = None) -> tuple[str, list]:
    """SQL predicate plus params restricting knowledge rows to the current profile.

    Unlabelled rows are included on purpose: a row whose profile is NULL predates
    the column or was written by an older mirror, and hiding it would silently
    delete real memory rather than scope it.
    """
    if include_all is None:
        include_all = scope_mode() == "all"
    if include_all:
        return "1 = 1", []
    column = f"{alias}.profile" if alias else "profile"
    return f"({column} = ? OR {column} IS NULL)", [current_profile()]
