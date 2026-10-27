#!/usr/bin/env python3
"""
Skill Manager Tool -- Agent-Managed Skill Creation & Editing

Allows the agent to create, update, and delete skills, turning successful
approaches into reusable procedural knowledge. New skills are created in
~/.joshaico/skills/. Existing skills (bundled, hub-installed, or user-created)
can be modified or deleted wherever they live.

Skills are the agent's procedural memory: they capture *how to do a specific
type of task* based on proven experience. General memory (MEMORY.md, USER.md) is
broad and declarative. Skills are narrow and actionable.

Actions:
  create     -- Create a new skill (SKILL.md + directory structure)
  edit       -- Replace the SKILL.md content of a user skill (full rewrite)
  patch      -- Targeted find-and-replace within SKILL.md or any supporting file
  delete     -- Remove a user skill entirely
  write_file -- Add/overwrite a supporting file (reference, template, script, asset)
  remove_file-- Remove a supporting file from a user skill
  import    -- Import a skill from the bundled library into the local set + PG

Directory layout for user skills:
    ~/.joshaico/skills/
    ├── my-skill/
    │   ├── SKILL.md
    │   ├── references/
    │   ├── templates/
    │   ├── scripts/
    │   └── assets/
    └── category-name/
        └── another-skill/
            └── SKILL.md
"""

import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from joshaico_constants import get_joshaico_home, display_joshaico_home
from typing import Dict, Any, List, Optional, Tuple

from utils import atomic_replace, is_truthy_value
from joshaico_cli.config import cfg_get

# JPM PG availability — skills table is primary store for skill content
_JPM_AVAILABLE = False
_jpm_upsert_skill = None
try:
    from jpm.core._pg import is_pg_enabled
    from jpm.core._write import _upsert_skill as _jpm_upsert_skill
    _JPM_AVAILABLE = is_pg_enabled()
except Exception:
    pass

logger = logging.getLogger(__name__)


def _jpm_sync_skill(
    name: str,
    content: str,
    description: str = "",
    files: str = "{}",
    category: str = "",
    file_path: str = "",
    internal: Optional[bool] = None,
) -> bool:
    """Write skill content to DB as primary store.

    Returns True on success, False on failure (caller should abort the
    disk write if this fails — DB is the source of truth).
    """
    if not _JPM_AVAILABLE or not _jpm_upsert_skill:
        return False
    try:
        # Preserve the existing file_path when the caller doesn't supply one.
        # Every patch/edit path calls this without file_path, and _upsert_skill's
        # ON CONFLICT ... file_path = excluded.file_path would otherwise null it
        # (excluded.file_path defaults to ""). That silently un-links a disk-backed
        # skill from its on-disk SKILL.md on every content edit. Only the create
        # path passes a real file_path; everything else must keep the stored one.
        if not file_path:
            try:
                from jpm.core._pg import sync_conn
                with sync_conn() as conn:
                    row = conn.fetchone(
                        "SELECT file_path FROM skills WHERE name = ? LIMIT 1",
                        (name,)
                    )
                    if row and row["file_path"]:
                        file_path = row["file_path"]
            except Exception:
                logger.debug("_jpm_sync_skill file_path lookup failed for %s", name, exc_info=True)
        _jpm_upsert_skill(
            name,
            content,
            description=description,
            files=files,
            category=category,
            file_path=file_path,
            internal=internal,
        )
        # Persist supporting files to the skill_files table (primary store).
        # _upsert_skill ignores its files= arg, so we write the table here.
        # Guard: only rewrite when the caller supplies a non-empty map —
        # plain content edits pass files="{}" and must NOT wipe existing
        # supporting files.
        try:
            parsed = json.loads(files)
            if isinstance(parsed, dict) and parsed:
                _jpm_write_skill_files(name, parsed)
        except Exception:
            logger.debug("_jpm_sync_skill file-map write failed for %s", name, exc_info=True)
        return True
    except Exception:
        logger.debug("_jpm_sync_skill failed for %s", name, exc_info=True)
        return False


def _jpm_fetch_skill(name: str) -> Optional[str]:
    """Read skill content from DB by name. Returns None if not found."""
    if not _JPM_AVAILABLE:
        return None
    try:
        from jpm.core._pg import sync_conn
        with sync_conn() as conn:
            row = conn.fetchone(
                "SELECT content FROM skills WHERE name = ? LIMIT 1",
                (name,)
            )
            return row["content"] if row else None
    except Exception:
        logger.debug("_jpm_fetch_skill failed for %s", name, exc_info=True)
        return None


def _jpm_fetch_skill_category(name: str) -> str:
    """Read the stored category for a skill from DB by name.

    Used by edit/patch to PRESERVE the category across updates. Without this,
    _upsert_skill's ``ON CONFLICT(name) DO UPDATE SET category = excluded.category``
    would wipe the stored category to ``""`` on every content edit.
    """
    if not _JPM_AVAILABLE:
        return ""
    try:
        from jpm.core._pg import sync_conn
        with sync_conn() as conn:
            row = conn.fetchone(
                "SELECT category FROM skills WHERE name = ? LIMIT 1",
                (name,)
            )
            return str(row["category"] or "") if row else ""
    except Exception:
        logger.debug("_jpm_fetch_skill_category failed for %s", name, exc_info=True)
        return ""


def _jpm_fetch_skill_files(name: str) -> dict:
    """Read the files map {file_path: content} for a skill from the
    skill_files table (primary store). Returns {} on failure."""
    if not _JPM_AVAILABLE:
        return {}
    try:
        from jpm.core._pg import sync_conn
        with sync_conn() as conn:
            rows = conn.fetchall(
                "SELECT file_path, content FROM skill_files "
                "WHERE skill_id = (SELECT id FROM skills WHERE name = ?)",
                (name,),
            )
            return {r["file_path"]: r["content"] for r in rows}
    except Exception:
        logger.debug("_jpm_fetch_skill_files failed for %s", name, exc_info=True)
        return {}


def _jpm_write_skill_files(name: str, files: dict) -> bool:
    """Replace all skill_files rows for a skill with the given map.
    DB is the primary store. Returns True on success."""
    if not _JPM_AVAILABLE:
        return False
    try:
        from jpm.core._pg import sync_conn
        with sync_conn() as conn:
            conn.execute(
                "DELETE FROM skill_files WHERE skill_id = "
                "(SELECT id FROM skills WHERE name = ?)",
                (name,),
            )
            for fp, content in files.items():
                conn.execute(
                    "INSERT INTO skill_files (skill_id, file_path, content) "
                    "VALUES ((SELECT id FROM skills WHERE name = ?), ?, ?)",
                    (name, fp, content),
                )
        return True
    except Exception:
        logger.debug("_jpm_write_skill_files failed for %s", name, exc_info=True)
        return False


def _jpm_remove_skill(name: str) -> None:
    """Remove a skill from the DB (called after disk delete)."""
    if not _JPM_AVAILABLE:
        return
    try:
        from jpm.core._pg import sync_conn
        with sync_conn() as conn:
            conn.execute("DELETE FROM skills WHERE name = ?", (name,))
        from jpm.core._cache import _get_cache as _jpm_cache
        _jpm_cache().invalidate("knowledge_")
    except Exception:
        pass

# Import security scanner — external hub installs always get scanned;
# agent-created skills only get scanned when skills.guard_agent_created is on.
try:
    from tools.skills_guard import scan_skill, should_allow_install, format_scan_report
    _GUARD_AVAILABLE = True
except ImportError:
    _GUARD_AVAILABLE = False


def _guard_agent_created_enabled() -> bool:
    """Read skills.guard_agent_created from config (default False).

    Off by default because the agent can already execute the same code
    paths via terminal() with no gate, so the scan adds friction without
    meaningful security.  Users who want belt-and-suspenders can turn it
    on via `joshaico config set skills.guard_agent_created true`.
    """
    try:
        from joshaico_cli.config import load_config
        cfg = load_config()
        return is_truthy_value(
            cfg_get(cfg, "skills", "guard_agent_created"),
            default=False,
        )
    except Exception:
        return False


def _security_scan_skill(skill_dir: Path) -> Optional[str]:
    """Scan a skill directory after write. Returns error string if blocked, else None.

    No-op when skills.guard_agent_created is disabled (the default).
    """
    if not _GUARD_AVAILABLE:
        return None
    if not _guard_agent_created_enabled():
        return None
    try:
        result = scan_skill(skill_dir, source="agent-created")
        allowed, reason = should_allow_install(result)
        if allowed is False:
            report = format_scan_report(result)
            return f"Security scan blocked this skill ({reason}):\n{report}"
        if allowed is None:
            # "ask" verdict — for agent-created skills this means dangerous
            # findings were detected.  Surface as an error so the agent can
            # retry with the flagged content removed.
            report = format_scan_report(result)
            logger.warning("Agent-created skill blocked (dangerous findings): %s", reason)
            return f"Security scan blocked this skill ({reason}):\n{report}"
    except Exception as e:
        logger.warning("Security scan failed for %s: %s", skill_dir, e, exc_info=True)
    return None

import yaml


# All skills live in ~/.joshaico/skills/ (single source of truth)
JOSHAICO_HOME = get_joshaico_home()
SKILLS_DIR = JOSHAICO_HOME / "skills"

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024


def _containing_skills_root(skill_path: Path) -> Path:
    """Return the skills root directory (local or external_dirs entry) that
    contains ``skill_path``.  Falls back to the local ``SKILLS_DIR`` if no
    match is found (defensive — callers should have located the skill via
    ``_find_skill`` first).
    """
    from agent.skill_utils import get_all_skills_dirs

    try:
        resolved = skill_path.resolve()
    except OSError:
        resolved = skill_path

    for root in get_all_skills_dirs():
        try:
            resolved.relative_to(root.resolve())
            return root
        except (ValueError, OSError):
            continue
    return SKILLS_DIR


def _is_path_redirect(path: Path) -> bool:
    """True when ``path`` is a symlink or (on Windows) a directory junction.

    Either form lets a poisoned skills tree redirect a subsequent
    ``shutil.rmtree`` to content outside the skills root. ``is_junction``
    only exists on Python 3.12+ Windows; gate with ``hasattr``.
    """
    try:
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
    except OSError:
        return False


def _validate_delete_target(skill_dir: Path) -> Optional[str]:
    """Last-line guard before ``shutil.rmtree(skill_dir)`` in ``_delete_skill``.

    ``_find_skill`` already restricts ``skill_dir`` to a real ``SKILL.md``
    parent discovered by walking the skills roots, so the agent cannot inject
    an arbitrary path the way Kilo Code's HTTP endpoint could (their issue
    #11227: a built-in-skill sentinel resolved to the server cwd and a
    recursive delete wiped the user's entire working directory). This is the
    matching defense-in-depth for our agent-facing ``skill_manage`` delete
    path: even if discovery or a poisoned tree hands us a bad directory, never
    recursively delete

      1. a path that is not strictly *inside* one of the known skills roots,
      2. a skills root itself (would wipe every installed skill), or
      3. a directory reached via a symlink / junction (``rmtree`` would follow
         it into content outside the skills tree).

    Returns an error string to refuse on, or ``None`` when the delete is safe.
    """
    from agent.skill_utils import get_all_skills_dirs

    # (3) Reject symlink/junction redirects on the skill directory itself.
    if _is_path_redirect(skill_dir):
        return (
            f"Refusing to delete '{skill_dir}': the skill directory is a "
            f"symlink/junction. Remove the link target manually if intended."
        )

    try:
        resolved = skill_dir.resolve()
    except OSError as exc:
        return f"Refusing to delete '{skill_dir}': could not resolve path ({exc})."

    roots = []
    for root in get_all_skills_dirs():
        try:
            roots.append(root.resolve())
        except OSError:
            continue

    for root in roots:
        # (2) Never rmtree a skills root itself.
        if resolved == root:
            return (
                f"Refusing to delete '{skill_dir}': resolves to the skills root "
                f"itself, which would remove every installed skill."
            )
        # (1) Must be strictly inside a known root.
        try:
            rel = resolved.relative_to(root)
        except ValueError:
            continue
        if rel.parts:  # at least one component below the root
            return None

    return (
        f"Refusing to delete '{skill_dir}': path does not resolve inside any "
        f"known skills root."
    )


def _pinned_guard(name: str) -> Optional[str]:
    """Return a refusal message if *name* is pinned, else None.

    Pin protects a skill from **deletion** — both the curator's auto-archive
    passes and the agent's ``skill_manage(action="delete")`` tool call. The
    agent can still patch/edit pinned skills; pin only guards against
    irrecoverable loss, not against content evolution.

    Best-effort: if the sidecar is unreadable we let the delete through
    rather than block on a broken telemetry file.
    """
    try:
        from tools import skill_usage
        rec = skill_usage.get_record(name)
        if rec.get("pinned"):
            return (
                f"Skill '{name}' is pinned and cannot be deleted by "
                f"skill_manage. Ask the user to run "
                f"`joshaico curator unpin {name}` if they want to delete it. "
                f"Patches and edits are allowed on pinned skills; only "
                f"deletion is blocked."
            )
    except Exception:
        logger.debug("pinned-guard lookup failed for %s", name, exc_info=True)
    return None


def _background_review_write_guard(
    name: str,
    skill_dir: Path,
    action: str,
) -> Optional[Dict[str, Any]]:
    """Refuse autonomous curator writes to externally owned skills.

    Foreground agents may still perform user-directed edits to external,
    bundled, or hub-installed skills. The background review fork is different:
    it is autonomous lifecycle maintenance, so its write surface is restricted
    to local curator-owned sediment.
    """
    try:
        from tools.skill_provenance import is_background_review
        if not is_background_review():
            return None
    except Exception:
        return None

    # Pin must be respected by autonomous maintenance. The curator already
    # skips pinned skills from every auto-transition; the background review
    # fork is the same kind of autonomous, no-user-present actor, so it must
    # not write to a pinned skill either (issue #25839). This is stricter than
    # the foreground ``_pinned_guard`` (which only blocks deletion) precisely
    # because there is no user in the loop to consent to an edit here.
    try:
        from tools import skill_usage
        if skill_usage.get_record(name).get("pinned"):
            return {
                "success": False,
                "error": (
                    f"Refusing background curator {action} for pinned skill "
                    f"'{name}': pinned skills are off-limits to autonomous "
                    "maintenance. Ask the user to run "
                    f"`joshaico curator unpin {name}` if they want it changed."
                ),
            }
    except Exception:
        logger.debug("pinned skill guard lookup failed for %s", name, exc_info=True)

    try:
        from agent.skill_utils import is_external_skill_path
        if is_external_skill_path(skill_dir):
            return {
                "success": False,
                "error": (
                    f"Refusing background curator {action} for skill '{name}': "
                    "the skill lives in skills.external_dirs, which are "
                    "externally owned and read-only to autonomous curation."
                ),
            }
    except Exception:
        logger.debug("external skill guard lookup failed for %s", name, exc_info=True)

    try:
        from tools import skill_usage
        if skill_usage.is_protected_builtin(name):
            return {
                "success": False,
                "error": (
                    f"Refusing background curator {action} for protected "
                    f"built-in skill '{name}'."
                ),
            }
        if skill_usage.is_hub_installed(name):
            return {
                "success": False,
                "error": (
                    f"Refusing background curator {action} for hub-installed "
                    f"skill '{name}'."
                ),
            }
        if skill_usage.is_bundled(name):
            return {
                "success": False,
                "error": (
                    f"Refusing background curator {action} for bundled "
                    f"skill '{name}'."
                ),
            }
    except Exception:
        logger.debug("owned skill guard lookup failed for %s", name, exc_info=True)
    return None


def _background_review_preflight(action: str, name: str) -> Optional[Dict[str, Any]]:
    if action not in {"edit", "patch", "delete", "write_file", "remove_file"}:
        return None
    existing = _find_skill(name)
    if not existing:
        return None
    return _background_review_write_guard(name, existing["path"], action)


def _curator_consolidation_delete_guard(
    name: str, absorbed_into: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Fail closed on unverified deletes during the curator consolidation pass.

    The curator's forked review agent (``is_background_review()``) runs the
    LLM umbrella-building pass. Its only legitimate ``skill_manage(delete)`` is
    a *verified consolidation*: the skill's content was absorbed into an
    umbrella, declared via ``absorbed_into=<umbrella>`` where the umbrella
    exists on disk (validated separately in ``_delete_skill``).

    A delete with no forwarding target — ``absorbed_into`` omitted (``None``)
    or empty (``""``) — is the fail-open behavior reported in #29912: the
    consolidation pass archived whole clusters of active skills with zero
    verified consolidations (``consolidated_this_run == 0``), leaving active
    automations pointing at names that no longer resolve. The deterministic
    inactivity prune is the only legitimate prune path, and it archives via
    ``skill_usage.archive_skill()`` directly without ever calling
    ``skill_manage`` — so a bare prune reaching here can only be the LLM pass
    pruning without consolidation evidence. Refuse it; keep the skill active.

    Returns an error dict to abort the delete, or ``None`` when the delete is
    allowed to proceed (not the curator pass, or a declared consolidation).
    """
    try:
        from tools.skill_provenance import is_background_review
        if not is_background_review():
            return None
    except Exception:
        return None

    declared = isinstance(absorbed_into, str) and absorbed_into.strip()
    if declared:
        return None

    return {
        "success": False,
        "error": (
            f"Refusing background curator delete of skill '{name}': the "
            "consolidation pass may only archive a skill it has absorbed into "
            "an umbrella. Pass absorbed_into=<umbrella> (the umbrella must "
            "already exist) to record a verified consolidation. Pruning a "
            "skill with no forwarding target is not permitted here — the "
            "deterministic inactivity prune handles staleness archival "
            "separately. Keeping '{name}' active.".format(name=name)
        ),
        "_fail_closed": True,
    }


MAX_SKILL_CONTENT_CHARS = 100_000   # ~36k tokens at 2.75 chars/token
MAX_SKILL_FILE_BYTES = 1_048_576    # 1 MiB per supporting file

# Characters allowed in skill names (filesystem-safe, URL-friendly)
VALID_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9._-]*$')

# Subdirectories allowed for write_file/remove_file
ALLOWED_SUBDIRS = {"references", "templates", "scripts", "assets"}


# =============================================================================
# Validation helpers
# =============================================================================

def _validate_name(name: str) -> Optional[str]:
    """Validate a skill name. Returns error message or None if valid."""
    if not name:
        return "Skill name is required."
    if len(name) > MAX_NAME_LENGTH:
        return f"Skill name exceeds {MAX_NAME_LENGTH} characters."
    if not VALID_NAME_RE.match(name):
        return (
            f"Invalid skill name '{name}'. Use lowercase letters, numbers, "
            f"hyphens, dots, and underscores. Must start with a letter or digit."
        )
    return None


def _validate_category(category: Optional[str]) -> Optional[str]:
    """Validate an optional category name used as a single directory segment."""
    if category is None:
        return None
    if not isinstance(category, str):
        return "Category must be a string."

    category = category.strip()
    if not category:
        return None
    if "/" in category or "\\" in category:
        return (
            f"Invalid category '{category}'. Use lowercase letters, numbers, "
            "hyphens, dots, and underscores. Categories must be a single directory name."
        )
    if len(category) > MAX_NAME_LENGTH:
        return f"Category exceeds {MAX_NAME_LENGTH} characters."
    if not VALID_NAME_RE.match(category):
        return (
            f"Invalid category '{category}'. Use lowercase letters, numbers, "
            "hyphens, dots, and underscores. Categories must be a single directory name."
        )
    return None


def _validate_frontmatter(content: str) -> Optional[str]:
    """
    Validate that SKILL.md content has proper frontmatter with required fields.
    Returns error message or None if valid.
    """
    if not content.strip():
        return "Content cannot be empty."

    if not content.startswith("---"):
        return "SKILL.md must start with YAML frontmatter (---). See existing skills for format."

    end_match = re.search(r'\n---\s*\n', content[3:])
    if not end_match:
        return "SKILL.md frontmatter is not closed. Ensure you have a closing '---' line."

    yaml_content = content[3:end_match.start() + 3]

    try:
        parsed = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        return f"YAML frontmatter parse error: {e}"

    if not isinstance(parsed, dict):
        return "Frontmatter must be a YAML mapping (key: value pairs)."

    if "name" not in parsed:
        return "Frontmatter must include 'name' field."
    if "description" not in parsed:
        return "Frontmatter must include 'description' field."
    if len(str(parsed["description"])) > MAX_DESCRIPTION_LENGTH:
        return f"Description exceeds {MAX_DESCRIPTION_LENGTH} characters."

    # Tags are required for searchability. Canonical locations (in priority
    # order, matching skills_tool / skills_hub search): metadata.joshaico.tags,
    # metadata.joshaico.tags, then top-level 'tags'. All are consumed by search.
    _tags = None
    _metadata = parsed.get("metadata")
    if isinstance(_metadata, dict):
        for _ns in ("joshaico",):
            _ns_meta = _metadata.get(_ns, {})
            if isinstance(_ns_meta, dict) and _ns_meta.get("tags"):
                _tags = _ns_meta.get("tags")
                break
    if not _tags:
        _tags = parsed.get("tags")
    if not _tags:
        return (
            "Frontmatter must include tags for searchability. Add "
            "'metadata:\\n  joshaico:\\n    tags: [tag1, tag2]' (or a top-level "
            "'tags: [tag1, tag2]' list) with at least one keyword."
        )
    if isinstance(_tags, str):
        _tags = [t.strip() for t in _tags.strip("[]").split(",") if t.strip()]
    if not isinstance(_tags, list) or not _tags:
        return (
            "Frontmatter 'tags' must be a non-empty list of keywords "
            "(e.g. 'tags: [research, pricing]')."
        )

    body = content[end_match.end() + 3:].strip()
    if not body:
        return "SKILL.md must have content after the frontmatter (instructions, procedures, etc.)."

    return None


def _validate_content_size(content: str, label: str = "SKILL.md") -> Optional[str]:
    """Check that content doesn't exceed the character limit for agent writes.

    Returns an error message or None if within bounds.
    """
    if len(content) > MAX_SKILL_CONTENT_CHARS:
        return (
            f"{label} content is {len(content):,} characters "
            f"(limit: {MAX_SKILL_CONTENT_CHARS:,}). "
            f"Consider splitting into a smaller SKILL.md with supporting files "
            f"in references/ or templates/."
        )
    return None


# Internal categories whose skills sync back to the shared core pool. Used
# solely to set the ``internal`` DB flag (see ``_create_skill``) — it no
# longer shapes the on-disk path.
_INTERNAL_CATEGORIES = {"joshaico-agent", "joshaico-agent/internal"}


def _resolve_skill_dir(name: str, category: str = None) -> Path:
    """Build the directory path for a new skill — ONE rule, shared with the mirror.

    This MUST produce the same path as ``pg_skills_to_home.py::dest_relpath``
    (the PG→disk mirror), because that script is the authority that lays the
    tree down from PG. When the two disagreed, ``create(category='devops')``
    wrote disk to ``custom-agent/<name>/`` while PG recorded category
    ``devops`` and a ``file_path`` pointing into the wrong tree — so the next
    mirror run also wrote ``devops/<name>/`` and the skill existed in two
    places with a blank/drifted link. Unified rule:

        non-empty category -> ``SKILLS_DIR / <category> / <name>``
        empty category     -> ``SKILLS_DIR / <name>``  (flat, uncategorized)

    ``custom-agent`` is just an ordinary category under this rule (PG already
    carries ``custom-agent`` rows), not a catch-all fallback.

    Only *new* creates route through here (see ``_create_skill``); existing
    skills are located by ``_find_skill`` and keep their current location,
    so this never relocates a skill that already exists.
    """
    cat = (category or "").strip()
    if cat:
        return SKILLS_DIR / cat / name
    return SKILLS_DIR / name


def _find_skill_on_disk(name: str) -> Optional[Path]:
    """Locate ``name``'s on-disk skill dir, or None if it has no SKILL.md.

    Checks every skills dir (local ``~/.joshaico/skills/`` first, then
    external dirs). Used to decide whether a write can be dual-write
    (DB + disk) or must stay DB-only (no phantom dirs on disk).
    """
    try:
        from agent.skill_utils import get_all_skills_dirs, is_excluded_skill_path
    except Exception:
        return None
    for skills_dir in get_all_skills_dirs():
        if not skills_dir.exists():
            continue
        for skill_md in skills_dir.rglob("SKILL.md"):
            try:
                if is_excluded_skill_path(skill_md):
                    continue
            except Exception:
                continue
            if skill_md.parent.name == name:
                return skill_md.parent
    return None


def _skill_dir_from_file_path(name: str) -> Optional[Path]:
    """Resolve a skill's on-disk dir from the ``skills.file_path`` column.

    ``file_path`` is the authoritative PG→disk link, backfilled by
    ``pg_skills_to_home.py``. It lets a DB-found skill still dual-write even
    when recursive disk discovery misses (new category layout, renamed dirs).
    Returns the parent dir only when ``file_path`` points at an existing
    SKILL.md that sits inside a known skills root — a stale or foreign path
    must never redirect a write outside the skills tree.
    """
    if not _JPM_AVAILABLE:
        return None
    try:
        from jpm.core._pg import sync_conn
        with sync_conn() as conn:
            row = conn.fetchone(
                "SELECT file_path FROM skills WHERE name = ? LIMIT 1",
                (name,),
            )
    except Exception:
        return None
    path = row["file_path"] if row else None
    if not path:
        return None
    try:
        skill_md = Path(path)
        if not skill_md.is_file() or skill_md.name != "SKILL.md":
            return None
        skill_dir = skill_md.parent
        resolved = skill_dir.resolve()
        from agent.skill_utils import get_all_skills_dirs
        for root in get_all_skills_dirs():
            try:
                resolved.relative_to(root.resolve())
                return skill_dir
            except (ValueError, OSError):
                continue
    except Exception:
        return None
    return None


def _find_skill(name: str) -> Optional[Dict[str, Any]]:
    """
    Find a skill by name — DB first, disk path resolved for dual-write.

    DB is the primary store. When the skill exists in the DB AND a
    matching SKILL.md exists on disk, returns a real ``path`` so
    foreground writes can update both. When it only exists in the DB
    (no on-disk SKILL.md), returns ``{"path": None, "_db_only": True}``
    and writes stay DB-only (no phantom dirs created). Falls back to
    disk-only lookup for bundled/not-yet-synced skills.
    """
    db_found = False
    if _JPM_AVAILABLE:
        try:
            from jpm.core._pg import sync_conn
            with sync_conn() as conn:
                row = conn.fetchone(
                    "SELECT name FROM skills WHERE name = ? LIMIT 1",
                    (name,)
                )
            db_found = bool(row)
        except Exception:
            pass

    if db_found:
        disk = _find_skill_on_disk(name)
        if disk is not None:
            return {"path": disk, "_db_only": False}
        # Recursive discovery missed — fall back to the stored file_path.
        fp_dir = _skill_dir_from_file_path(name)
        if fp_dir is not None:
            return {"path": fp_dir, "_db_only": False}
        return {"path": None, "_db_only": True}

    # Not in DB — fall back to disk (bundled / pre-migration installs).
    disk = _find_skill_on_disk(name)
    if disk is not None:
        return {"path": disk, "_db_only": False}
    return None


def _find_skill_in_other_profiles(name: str) -> List[Tuple[str, Path]]:
    """Look for ``name`` under SKILL.md across OTHER Joshaico profiles.

    Returns a list of ``(profile_name, skill_dir)`` pairs. Used to make
    the "Skill X not found" error explain when the user is editing the
    wrong profile. Empty list when no other profile has the skill (or
    when profile discovery fails — fail-quiet, the caller falls back to
    the plain "not found" error).
    """
    matches: List[Tuple[str, Path]] = []
    try:
        from joshaico_constants import get_default_joshaico_root
        from agent.skill_utils import is_excluded_skill_path
    except Exception:
        return matches

    try:
        root = get_default_joshaico_root()
    except Exception:
        return matches

    # Collect (profile_name, skills_dir) for every profile EXCEPT the
    # one whose SKILLS_DIR we already searched in _find_skill().
    active_dir = SKILLS_DIR.resolve() if SKILLS_DIR.exists() else SKILLS_DIR
    candidates: List[Tuple[str, Path]] = []

    # Default profile (~/.joshaico/skills) — only consider when active is non-default.
    default_skills = root / "skills"
    try:
        if default_skills.resolve() != active_dir:
            candidates.append(("default", default_skills))
    except (OSError, RuntimeError):
        pass

    # All named profiles (~/.joshaico/profiles/*/skills)
    profiles_root = root / "profiles"
    if profiles_root.is_dir():
        try:
            for entry in profiles_root.iterdir():
                if not entry.is_dir():
                    continue
                pskills = entry / "skills"
                try:
                    if pskills.resolve() == active_dir:
                        continue
                except (OSError, RuntimeError):
                    continue
                candidates.append((entry.name, pskills))
        except OSError:
            pass

    for profile_name, skills_dir in candidates:
        if not skills_dir.is_dir():
            continue
        try:
            for skill_md in skills_dir.rglob("SKILL.md"):
                if is_excluded_skill_path(skill_md):
                    continue
                if skill_md.parent.name == name:
                    matches.append((profile_name, skill_md.parent))
                    break  # one match per profile is enough
        except OSError:
            continue
    return matches


def _skill_not_found_error(name: str, suffix: str = "") -> str:
    """Build a "skill not found" error that names other profiles holding
    the same skill, so the agent can recognize a profile-scoping mistake.

    ``suffix`` is appended after the cross-profile hint if present
    (e.g. ``" Create it first with action='create'."``).
    """
    from agent.file_safety import _resolve_active_profile_name
    active = _resolve_active_profile_name()
    base = f"Skill '{name}' not found in active profile '{active}'."

    others = _find_skill_in_other_profiles(name)
    if others:
        if len(others) == 1:
            other_profile, other_path = others[0]
            base += (
                f" A skill by that name exists in profile "
                f"'{other_profile}' ({other_path}). To edit a skill in "
                f"another profile, switch profiles (`joshaico -p "
                f"{other_profile}`) or operate via explicit file tools "
                f"with ``cross_profile=True``."
            )
        else:
            names = ", ".join(f"'{p}'" for p, _ in others)
            base += (
                f" Skills by that name exist in other profiles: {names}. "
                f"Switch profiles (`joshaico -p <name>`) to edit there, or "
                f"operate via explicit file tools with ``cross_profile=True``."
            )
    else:
        base += " Use skills_list() to see available skills."

    if suffix:
        base += suffix
    return base


def _validate_file_path(file_path: str) -> Optional[str]:
    """
    Validate a file path for write_file/remove_file.
    Must be under an allowed subdirectory and not escape the skill dir.
    """
    from tools.path_security import has_traversal_component

    if not file_path:
        return "file_path is required."

    normalized = Path(file_path)

    # Prevent path traversal (checked before any allow-listing so the SKILL.md
    # exception below can never be reached by a traversal-laden path).
    if has_traversal_component(file_path):
        return "Path traversal ('..') is not allowed."

    # SKILL.md is the canonical skill file and lives at the skill root, not
    # under an allowed subdirectory. Accept its two natural spellings —
    # 'SKILL.md' and '<skill-name>/SKILL.md' — so callers can target the main
    # file. The traversal guard above still applies, so this can't escape.
    if normalized.parts and normalized.name == "SKILL.md":
        if len(normalized.parts) == 1 or len(normalized.parts) == 2:
            return None

    # Must be under an allowed subdirectory
    if not normalized.parts or normalized.parts[0] not in ALLOWED_SUBDIRS:
        allowed = ", ".join(sorted(ALLOWED_SUBDIRS))
        return f"File must be under one of: {allowed}. Got: '{file_path}'"

    # Must have a filename (not just a directory)
    if len(normalized.parts) < 2:
        return f"Provide a file path, not just a directory. Example: '{normalized.parts[0]}/myfile.md'"

    return None


def _resolve_skill_target(skill_dir: Path, file_path: str) -> Tuple[Optional[Path], Optional[str]]:
    """Resolve a supporting-file path and ensure it stays within the skill directory."""
    from tools.path_security import validate_within_dir

    target = skill_dir / file_path
    error = validate_within_dir(target, skill_dir)
    if error:
        return None, error
    return target, None


def _atomic_write_text(file_path: Path, content: str, encoding: str = "utf-8") -> None:
    """
    Atomically write text content to a file.
    
    Uses a temporary file in the same directory and os.replace() to ensure
    the target file is never left in a partially-written state if the process
    crashes or is interrupted.
    
    Args:
        file_path: Target file path
        content: Content to write
        encoding: Text encoding (default: utf-8)
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        dir=str(file_path.parent),
        prefix=f".{file_path.name}.tmp.",
        suffix="",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        # mkstemp creates the temp file at 0600 and os.replace preserves that
        # mode, so without this every skill file lands at 600 — unreadable by
        # any process that isn't the owner (end-user bots, other agents), and
        # the import/read failure is swallowed at DEBUG. Match the repo
        # convention (git records 100644) and the process umask.
        try:
            umask = os.umask(0)
            os.umask(umask)
            os.chmod(temp_path, 0o666 & ~umask)
        except OSError:
            logger.debug("Failed to chmod temp file %s", temp_path, exc_info=True)
        atomic_replace(temp_path, file_path)
    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except OSError:
            logger.error("Failed to remove temporary file %s during atomic write", temp_path, exc_info=True)
        raise


def _should_skip_disk() -> bool:
    """True when a skill write should stay DB-only (skip the disk write).

    Two signals:
      * the ``_skill_db_only`` ContextVar (legacy; defaults to False now so
        foreground writes dual-write DB + disk), or
      * the background self-improvement / curator review fork, which is
        detected via ``is_background_review()`` and must not touch the
        filesystem (no "Patched SKILL.md" alerts, no dir churn).
    """
    if _skill_db_only.get():
        return True
    try:
        from tools.skill_provenance import is_background_review
        return is_background_review()
    except Exception:
        return False


# =============================================================================
# Core actions
# =============================================================================

def _create_skill(name: str, content: str, category: str = None) -> Dict[str, Any]:
    """Create a new user skill with SKILL.md content."""
    # Validate name
    err = _validate_name(name)
    if err:
        return {"success": False, "error": err}

    err = _validate_category(category)
    if err:
        return {"success": False, "error": err}

    # Validate content
    err = _validate_frontmatter(content)
    if err:
        return {"success": False, "error": err}

    err = _validate_content_size(content)
    if err:
        return {"success": False, "error": err}

    # Check for name collisions across all directories
    existing = _find_skill(name)
    if existing:
        return {
            "success": False,
            "error": f"A skill named '{name}' already exists at {existing['path']}."
        }

    # Create the skill directory
    skill_dir = _resolve_skill_dir(name, category)
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Extract description from frontmatter
    _desc = ""
    try:
        _fm_end = re.search(r'\n---\s*\n', content[3:])
        if _fm_end:
            _parsed = yaml.safe_load(content[3:_fm_end.start() + 3])
            _desc = str(_parsed.get("description", ""))
    except Exception:
        pass

    # DB first — write to PostgreSQL before disk.
    # Record the on-disk SKILL.md path for EVERY skill so `file_path` always
    # links the PG row to its mirror dir. `_find_skill` uses it as the
    # authoritative disk resolver, and `pg_skills_to_home.py` regenerates the
    # tree from it — leaving it blank for end-user skills is what let PG and
    # disk drift apart in the first place.
    _recorded_path = str(skill_dir / "SKILL.md")
    # `internal` mirrors the same category gate: joshaico-agent skills are
    # internal-only (never distributed to end-user bots), everything else
    # is a normal skill. The DB column is the queryable source of truth for
    # any sync/backfill that must keep internal skills out of end-user sets.
    _is_internal = bool(category and category in _INTERNAL_CATEGORIES)
    _db_ok = _jpm_sync_skill(
        name, content,
        description=_desc,
        files="{}",
        category=category or "",
        file_path=_recorded_path,
        internal=_is_internal,
    )
    if not _db_ok:
        shutil.rmtree(skill_dir, ignore_errors=True)
        return {"success": False, "error": "Failed to write skill to database. The skill was not created."}

    # When _should_skip_disk (background review or legacy ContextVar), skip disk writes entirely
    if _should_skip_disk():
        return {
            "success": True,
            "message": f"Skill '{name}' created (DB only).",
            "_db_only": True,
        }

    # Write SKILL.md atomically
    skill_md = skill_dir / "SKILL.md"
    _atomic_write_text(skill_md, content)

    # Security scan — roll back on block
    scan_error = _security_scan_skill(skill_dir)
    if scan_error:
        shutil.rmtree(skill_dir, ignore_errors=True)
        _jpm_remove_skill(name)
        return {"success": False, "error": scan_error}

    result = {
        "success": True,
        "message": f"Skill '{name}' created.",
        "path": str(skill_dir.relative_to(SKILLS_DIR)),
        "skill_md": str(skill_md),
        "_change": {"description": _desc},
    }
    if category:
        result["category"] = category
    result["hint"] = (
        "To add reference files, templates, or scripts, use "
        "skill_manage(action='write_file', name='{}', file_path='references/example.md', file_content='...')".format(name)
    )
    return result


def _edit_skill(name: str, content: str) -> Dict[str, Any]:
    """Replace the SKILL.md of any existing skill (full rewrite)."""
    err = _validate_frontmatter(content)
    if err:
        return {"success": False, "error": err}

    err = _validate_content_size(content)
    if err:
        return {"success": False, "error": err}

    existing = _find_skill(name)
    if not existing:
        return {"success": False, "error": _skill_not_found_error(name)}

    # DB-only skills — write to DB directly, no disk
    if existing.get("_db_only"):
        _desc = ""
        try:
            _fm_end = re.search(r'\n---\s*\n', content[3:])
            if _fm_end:
                _parsed = yaml.safe_load(content[3:_fm_end.start() + 3])
                _desc = str(_parsed.get("description", ""))
        except Exception:
            pass
        _jpm_sync_skill(name, content, description=_desc, files="{}", category=_jpm_fetch_skill_category(name))
        return {
            "success": True,
            "message": f"Skill '{name}' updated (DB only).",
            "_db_only": True,
        }

    guard = _background_review_write_guard(name, existing["path"], "edit")
    if guard:
        return guard

    skill_md = existing["path"] / "SKILL.md"
    # Back up original content for rollback
    original_content = skill_md.read_text(encoding="utf-8") if skill_md.exists() else None

    # Extract description from new content
    _desc = ""
    try:
        _fm_end = re.search(r'\n---\s*\n', content[3:])
        if _fm_end:
            _parsed = yaml.safe_load(content[3:_fm_end.start() + 3])
            _desc = str(_parsed.get("description", ""))
    except Exception:
        pass

    # DB first — write to PostgreSQL before disk
    _db_ok = _jpm_sync_skill(
        name, content,
        description=_desc,
        files="{}",
        category=_jpm_fetch_skill_category(name),
    )
    if not _db_ok:
        return {"success": False, "error": "Failed to write skill to database. Edit was not applied."}

    # When _should_skip_disk (background review), skip disk writes entirely
    if _should_skip_disk():
        return {
            "success": True,
            "message": f"Skill '{name}' updated (DB only).",
            "_db_only": True,
        }

    # Write SKILL.md atomically
    _atomic_write_text(skill_md, content)

    # Security scan — roll back on block
    scan_error = _security_scan_skill(existing["path"])
    if scan_error:
        if original_content is not None:
            _atomic_write_text(skill_md, original_content)
            # Restore DB to original content too
            _orig_desc = ""
            try:
                _ofm = re.search(r'\n---\s*\n', original_content[3:])
                if _ofm:
                    _oparsed = yaml.safe_load(original_content[3:_ofm.start() + 3])
                    _orig_desc = str(_oparsed.get("description", ""))
            except Exception:
                pass
            _jpm_sync_skill(
                name, original_content,
                description=_orig_desc,
                files="{}",
                category=_jpm_fetch_skill_category(name),
            )
        return {"success": False, "error": scan_error}

    return {
        "success": True,
        "message": f"Skill '{name}' updated (full rewrite).",
        "path": str(existing["path"]),
        "_change": {"description": _desc},
    }


def _patch_skill(
    name: str,
    old_string: str,
    new_string: str,
    file_path: str = None,
    replace_all: bool = False,
) -> Dict[str, Any]:
    """Targeted find-and-replace within a skill file.

    Defaults to SKILL.md. Use file_path to patch a supporting file instead.
    Requires a unique match unless replace_all is True.
    """
    if not old_string:
        return {"success": False, "error": "old_string is required for 'patch'."}
    if new_string is None:
        return {"success": False, "error": "new_string is required for 'patch'. Use an empty string to delete matched text."}

    existing = _find_skill(name)
    if not existing:
        return {"success": False, "error": _skill_not_found_error(name)}

    # DB-only skills — patch in memory, write to DB, no disk
    if existing.get("_db_only"):
        content = _jpm_fetch_skill(name)
        if content is None:
            return {"success": False, "error": f"Skill '{name}' found in DB but content is empty."}

        from tools.fuzzy_match import fuzzy_find_and_replace

        new_content, match_count, _strategy, match_error = fuzzy_find_and_replace(
            content, old_string, new_string, replace_all
        )
        if match_error:
            preview = content[:500] + ("..." if len(content) > 500 else "")
            err_msg = match_error
            try:
                from tools.fuzzy_match import format_no_match_hint
                err_msg += format_no_match_hint(match_error, match_count, old_string, content)
            except Exception:
                pass
            return {"success": False, "error": err_msg, "file_preview": preview}

        target_label = "SKILL.md" if not file_path else file_path
        err = _validate_content_size(new_content, label=target_label)
        if err:
            return {"success": False, "error": err}

        if not file_path:
            err = _validate_frontmatter(new_content)
            if err:
                return {"success": False, "error": f"Patch would break SKILL.md structure: {err}"}

        _desc = ""
        try:
            _fm_end = re.search(r'\n---\s*\n', new_content[3:])
            if _fm_end:
                _parsed = yaml.safe_load(new_content[3:_fm_end.start() + 3])
                _desc = str(_parsed.get("description", ""))
        except Exception:
            pass
        _jpm_sync_skill(name, new_content, description=_desc, files="{}", category=_jpm_fetch_skill_category(name))
        return {
            "success": True,
            "message": f"Patched {'SKILL.md' if not file_path else file_path} in skill '{name}' (DB only).",
            "_db_only": True,
        }

    skill_dir = existing["path"]
    guard = _background_review_write_guard(name, skill_dir, "patch")
    if guard:
        return guard

    if file_path:
        # Patching a supporting file
        err = _validate_file_path(file_path)
        if err:
            return {"success": False, "error": err}
        target, err = _resolve_skill_target(skill_dir, file_path)
        if err:
            return {"success": False, "error": err}
    else:
        # Patching SKILL.md
        target = skill_dir / "SKILL.md"

    if not target.exists():
        return {"success": False, "error": f"File not found: {target.relative_to(skill_dir)}"}

    content = target.read_text(encoding="utf-8")

    # Use the same fuzzy matching engine as the file patch tool.
    # This handles whitespace normalization, indentation differences,
    # escape sequences, and block-anchor matching — saving the agent
    # from exact-match failures on minor formatting mismatches.
    from tools.fuzzy_match import fuzzy_find_and_replace

    new_content, match_count, _strategy, match_error = fuzzy_find_and_replace(
        content, old_string, new_string, replace_all
    )
    if match_error:
        # Show a short preview of the file so the model can self-correct
        preview = content[:500] + ("..." if len(content) > 500 else "")
        err_msg = match_error
        try:
            from tools.fuzzy_match import format_no_match_hint
            err_msg += format_no_match_hint(match_error, match_count, old_string, content)
        except Exception:
            pass
        return {
            "success": False,
            "error": err_msg,
            "file_preview": preview,
        }

    # Check size limit on the result
    target_label = "SKILL.md" if not file_path else file_path
    err = _validate_content_size(new_content, label=target_label)
    if err:
        return {"success": False, "error": err}

    # If patching SKILL.md, validate frontmatter is still intact
    if not file_path:
        err = _validate_frontmatter(new_content)
        if err:
            return {
                "success": False,
                "error": f"Patch would break SKILL.md structure: {err}",
            }

    original_content = content  # for rollback

    # When _should_skip_disk (background review), write to DB only
    if _should_skip_disk():
        # Update DB with the patched content directly
        _desc = ""
        try:
            _fm_end = re.search(r'\n---\s*\n', new_content[3:])
            if _fm_end:
                _parsed = yaml.safe_load(new_content[3:_fm_end.start() + 3])
                _desc = str(_parsed.get("description", ""))
        except Exception:
            pass
        _jpm_sync_skill(
            name, new_content,
            description=_desc,
            files="{}",
            category=_jpm_fetch_skill_category(name),
        )
        return {
            "success": True,
            "message": f"Patched {'SKILL.md' if not file_path else file_path} in skill '{name}' (DB only).",
            "_db_only": True,
        }

    # DB first — sync the patched content to the primary store before disk.
    _desc = ""
    try:
        _fm_end = re.search(r'\n---\s*\n', new_content[3:])
        if _fm_end:
            _parsed = yaml.safe_load(new_content[3:_fm_end.start() + 3])
            _desc = str(_parsed.get("description", ""))
    except Exception:
        pass
    _db_ok = _jpm_sync_skill(
        name, new_content,
        description=_desc,
        files="{}",
        category=_jpm_fetch_skill_category(name),
    )
    if not _db_ok:
        return {"success": False, "error": "Failed to write patched skill to database. Patch was not applied."}

    _atomic_write_text(target, new_content)

    # Security scan — roll back on block
    scan_error = _security_scan_skill(skill_dir)
    if scan_error:
        _atomic_write_text(target, original_content)
        return {"success": False, "error": scan_error}

    result = {
        "success": True,
        "message": f"Patched {'SKILL.md' if not file_path else file_path} in skill '{name}' ({match_count} replacement{'s' if match_count > 1 else ''}).",
    }
    # Include change previews for verbose notifications
    result["_change"] = {
        "old": old_string[:200] + ("…" if len(old_string) > 200 else ""),
        "new": new_string[:200] + ("…" if len(new_string) > 200 else ""),
    }
    return result


def _delete_skill(name: str, absorbed_into: Optional[str] = None) -> Dict[str, Any]:
    """Delete a skill.

    ``absorbed_into`` declares intent:
      - ``None`` / missing  → caller didn't declare (legacy / non-curator path);
        accepted for backward compat but logs a warning because the curator
        classification pipeline can't tell consolidation from pruning without it.
      - ``""`` (empty)      → explicit "truly pruned, no forwarding target".
      - ``"<skill-name>"``  → content was absorbed into that umbrella; the
        target must exist on disk. Validated here so the model can't claim an
        umbrella that doesn't exist.
    """
    existing = _find_skill(name)
    if not existing:
        return {"success": False, "error": _skill_not_found_error(name)}

    # Fail closed on unverified deletes during the curator consolidation pass.
    # A bare prune (no absorbed_into) from the LLM umbrella pass is the
    # fail-open behavior reported in #29912 — refuse it; keep the skill active.
    # This guard runs for BOTH disk and DB-only skills: with DB now the primary
    # store, DB-only is the common case, so a bare curator prune must not
    # hard-remove the row without consolidation evidence.
    fail_closed = _curator_consolidation_delete_guard(name, absorbed_into)
    if fail_closed:
        return fail_closed

    pinned_err = _pinned_guard(name)
    if pinned_err:
        return {"success": False, "error": pinned_err}

    # DB-only skills — skip disk operations, just remove from DB
    if existing.get("_db_only"):
        _jpm_remove_skill(name)
        return {
            "success": True,
            "message": f"Skill '{name}' deleted (DB only).",
            "_db_only": True,
        }

    guard = _background_review_write_guard(name, existing["path"], "delete")
    if guard:
        return guard

    # Validate absorbed_into target when declared non-empty
    absorbed_target = (
        absorbed_into.strip()
        if absorbed_into is not None and isinstance(absorbed_into, str)
        else ""
    )
    is_consolidation = bool(absorbed_target)
    if is_consolidation:
        target_name = absorbed_target
        if target_name == name:
            return {
                "success": False,
                "error": f"absorbed_into='{target_name}' cannot equal the skill being deleted.",
            }
        target = _find_skill(target_name)
        if not target:
            return {
                "success": False,
                "error": (
                    f"absorbed_into='{target_name}' does not exist. "
                    f"Create or patch the umbrella skill first, then retry the delete."
                ),
            }

    skill_dir = existing["path"]
    skills_root = _containing_skills_root(skill_dir)

    # Defense-in-depth before the recursive delete (port of Kilo Code #11240).
    unsafe = _validate_delete_target(skill_dir)
    if unsafe:
        return {"success": False, "error": unsafe}

    # During the curator consolidation pass, a verified consolidation must be
    # RECOVERABLE: archival into ~/.joshaico/skills/.archive/ is documented as
    # the maximum destructive action the curator may take, and
    # `joshaico curator restore` promises the skill can be brought back. Route
    # through the recoverable archive primitive instead of permanent rmtree so
    # a misjudged consolidation can be undone (#29912). Foreground,
    # user-directed deletes keep their existing hard-delete semantics.
    try:
        from tools.skill_provenance import is_background_review
        curator_pass = is_background_review()
    except Exception:
        curator_pass = False

    if curator_pass:
        try:
            from tools.skill_usage import archive_skill
            ok, archive_msg = archive_skill(name)
        except Exception as e:
            return {"success": False, "error": f"failed to archive '{name}': {e}"}
        if not ok:
            return {"success": False, "error": archive_msg}
        message = f"Skill '{name}' archived ({archive_msg})."
        if is_consolidation:
            message += f" Content absorbed into '{absorbed_target}'."
        return {"success": True, "message": message, "_archived": True}

    shutil.rmtree(skill_dir)

    # Dual-write skills also have a DB row — remove it too so the skill is
    # fully deleted, not orphaned in the primary store.
    _jpm_remove_skill(name)

    # Clean up empty category directories (don't remove the skills root itself)
    parent = skill_dir.parent
    if parent != skills_root and parent.exists() and not any(parent.iterdir()):
        parent.rmdir()

    message = f"Skill '{name}' deleted."
    if is_consolidation:
        message += f" Content absorbed into '{absorbed_target}'."

    return {
        "success": True,
        "message": message,
    }


def _write_file(name: str, file_path: str, file_content: str) -> Dict[str, Any]:
    """Add or overwrite a supporting file within any skill directory."""
    err = _validate_file_path(file_path)
    if err:
        return {"success": False, "error": err}

    if not file_content and file_content != "":
        return {"success": False, "error": "file_content is required."}

    # Check size limits
    content_bytes = len(file_content.encode("utf-8"))
    if content_bytes > MAX_SKILL_FILE_BYTES:
        return {
            "success": False,
            "error": (
                f"File content is {content_bytes:,} bytes "
                f"(limit: {MAX_SKILL_FILE_BYTES:,} bytes / 1 MiB). "
                f"Consider splitting into smaller files."
            ),
        }
    err = _validate_content_size(file_content, label=file_path)
    if err:
        return {"success": False, "error": err}

    existing = _find_skill(name)
    if not existing:
        return {"success": False, "error": _skill_not_found_error(name, " Create it first with action='create'.")}

    # DB-only skills have no on-disk skill dir. Update the skill_files table
    # directly (no phantom dir on disk) — DB is the primary store.
    if existing.get("_db_only") or _should_skip_disk():
        _files = _jpm_fetch_skill_files(name)
        _files[file_path] = file_content
        _ok = _jpm_write_skill_files(name, _files)
        if not _ok:
            return {"success": False,
                    "error": f"Failed to register file '{file_path}' for DB-only skill '{name}'."}
        return {
            "success": True,
            "message": f"File '{file_path}' written to skill '{name}' (DB only).",
            "path": None,
        }

    skill_dir = existing.get("path")
    if skill_dir is None:
        return {"success": False, "error": _skill_not_found_error(name, " Create it first with action='create'.")}

    guard = _background_review_write_guard(name, skill_dir, "write_file")
    if guard:
        return guard

    target, err = _resolve_skill_target(skill_dir, file_path)
    if err:
        return {"success": False, "error": err}
    target.parent.mkdir(parents=True, exist_ok=True)
    # Back up for rollback
    original_content = target.read_text(encoding="utf-8") if target.exists() else None
    _atomic_write_text(target, file_content)

    # Security scan — roll back on block
    scan_error = _security_scan_skill(skill_dir)
    if scan_error:
        if original_content is not None:
            _atomic_write_text(target, original_content)
        else:
            target.unlink(missing_ok=True)
        return {"success": False, "error": scan_error}

    # Mirror to PG skill_files table (DB is the primary read path). If the
    # DB write fails, still report disk success but note the miss.
    _files = _jpm_fetch_skill_files(name)
    _files[file_path] = file_content
    _db_ok = _jpm_write_skill_files(name, _files)

    return {
        "success": True,
        "message": f"File '{file_path}' written to skill '{name}'." + ("" if _db_ok else " (DB sync failed.)"),
        "path": str(target),
    }


def _remove_file(name: str, file_path: str) -> Dict[str, Any]:
    """Remove a supporting file from any skill directory."""
    err = _validate_file_path(file_path)
    if err:
        return {"success": False, "error": err}

    existing = _find_skill(name)
    if not existing:
        return {"success": False, "error": _skill_not_found_error(name)}

    # DB-only skills have no on-disk skill dir. Update the skill_files table
    # directly (no phantom dir on disk) — DB is the primary store.
    if existing.get("_db_only") or _should_skip_disk():
        _files = _jpm_fetch_skill_files(name)
        if file_path not in _files:
            return {"success": False,
                    "error": f"File '{file_path}' not found in skill '{name}'.",
                    "available_files": sorted(_files.keys()) or None}
        del _files[file_path]
        _ok = _jpm_write_skill_files(name, _files)
        if not _ok:
            return {"success": False,
                    "error": f"Failed to remove file '{file_path}' from DB-only skill '{name}'."}
        return {
            "success": True,
            "message": f"File '{file_path}' removed from skill '{name}' (DB only).",
        }

    skill_dir = existing.get("path")
    if skill_dir is None:
        return {"success": False, "error": _skill_not_found_error(name)}

    guard = _background_review_write_guard(name, skill_dir, "remove_file")
    if guard:
        return guard

    target, err = _resolve_skill_target(skill_dir, file_path)
    if err:
        return {"success": False, "error": err}
    if not target.exists():
        # List what's actually there for the model to see
        available = []
        for subdir in ALLOWED_SUBDIRS:
            d = skill_dir / subdir
            if d.exists():
                for f in d.rglob("*"):
                    if f.is_file():
                        available.append(str(f.relative_to(skill_dir)))
        return {
            "success": False,
            "error": f"File '{file_path}' not found in skill '{name}'.",
            "available_files": available if available else None,
        }

    target.unlink()

    # Clean up empty subdirectories
    parent = target.parent
    if parent != skill_dir and parent.exists() and not any(parent.iterdir()):
        parent.rmdir()

    # Mirror to PG skill_files table (DB is the primary read path).
    _files = _jpm_fetch_skill_files(name)
    _files.pop(file_path, None)
    _db_ok = _jpm_write_skill_files(name, _files)

    return {
        "success": True,
        "message": f"File '{file_path}' removed from skill '{name}'." + ("" if _db_ok else " (DB sync failed.)"),
    }


def _find_library_skill(name: str) -> Optional[Path]:
    """Locate ``name`` in the bundled library by dir name (preferred) or
    frontmatter ``name:``. Skips backup/legacy dirs so a stale ``.legacy-bak``
    copy never shadows the real skill. Returns the skill's parent dir."""
    try:
        from tools.skills_sync import _get_bundled_dir
    except Exception:
        return None
    lib = _get_bundled_dir()
    if not lib.exists():
        return None
    direct = lib / name
    if direct.exists() and (direct / "SKILL.md").exists():
        return direct
    for skill_md in lib.rglob("SKILL.md"):
        parent = skill_md.parent
        if any(p.endswith((".legacy-bak", ".bak", ".old", ".archived", ".backup"))
               or p.startswith(".") for p in parent.relative_to(lib).parts):
            continue
        if parent.name == name:
            return parent
        # Frontmatter name fallback
        try:
            import yaml
            m = re.search(r"^---\n(.*?)\n---", skill_md.read_text(encoding="utf-8", errors="replace")[:4000], re.DOTALL)
            if m and str(yaml.safe_load(m.group(1)).get("name", "")) == name:
                return parent
        except Exception:
            continue
    return None


def _import_skill(name: str, category: str = None) -> Dict[str, Any]:
    """Import a skill from the bundled library into ~/.joshaico/skills/ and
    register it in the PG skills table (the primary read path).

    This is the opt-in replacement for the manual copy + backfill dance. It
    copies the library skill into ~/.joshaico/skills/ (flat, not under
    custom-agent/) and upserts it into PG, so the skill is immediately
    triggerable by name.
    """
    err = _validate_name(name)
    if err:
        return {"success": False, "error": err}

    if category is not None:
        err = _validate_category(category)
        if err:
            return {"success": False, "error": err}

    from tools.skills_sync import _get_bundled_dir, SKILLS_DIR

    lib = _get_bundled_dir()
    if lib is None or not lib.exists():
        return {"success": False,
                "error": f"Bundled skills directory not found: {lib}"}

    src = _find_library_skill(name)
    if src is None:
        # Offer a quick scan so the caller can pick the right identifier.
        available = sorted(
            p.parent.name for p in lib.rglob("SKILL.md")
            if not any(x.endswith((".legacy-bak", ".bak", ".old", ".archived", ".backup"))
                       or x.startswith(".") for x in p.parent.relative_to(lib).parts)
        )
        hint = f" Available: {', '.join(available[:40])}" if available else ""
        return {"success": False,
                "error": f"Skill '{name}' not found in the bundled library.{hint}"}

    # Imported skills are library-derived, not agent-created, so they land in
    # the canonical local skills dir (NOT under custom-agent/, which is reserved
    # for agent-created skills per convention #8). Category is preserved in PG.
    dest = SKILLS_DIR / name

    # Background review must not touch the filesystem (no dir churn) — register
    # in PG only.
    if _should_skip_disk():
        content = (src / "SKILL.md").read_text(encoding="utf-8", errors="replace")
        _desc = ""
        try:
            m = re.search(r"^---\n(.*?)\n---", content, re.DOTALL)
            if m:
                import yaml
                _desc = str(yaml.safe_load(m.group(1)).get("description", ""))[:1024]
        except Exception:
            pass
        _files = {}
        for _sd in ("references", "templates", "scripts", "assets"):
            _sub = src / _sd
            if _sub.exists() and _sub.is_dir():
                for _f in sorted(_sub.rglob("*")):
                    if _f.is_file():
                        try:
                            _files[str(_f.relative_to(src))] = _f.read_text(encoding="utf-8")
                        except Exception:
                            pass
        # Derive DB category from the library source path (preserved in PG
        # even though imported skills land flat under SKILLS_DIR).
        try:
            _rel = src.relative_to(lib)
            _cat = _rel.parts[0] if len(_rel.parts) >= 2 else ""
        except ValueError:
            _cat = ""
        if category:
            _cat = category
        _db_ok = _jpm_sync_skill(name, content, description=_desc,
                                 files=json.dumps(_files), category=_cat)
        msg = f"Skill '{name}' registered in PG (DB only, background)."
        if not _db_ok:
            msg += " (PG unavailable.)"
        return {"success": True, "action": "imported", "message": msg}

    already_local = dest.exists() and (dest / "SKILL.md").exists()
    if not already_local:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dest)
        except (OSError, IOError) as e:
            return {"success": False, "error": f"Failed to import '{name}': {e}"}

    # Register in PG (primary read path) so it's triggerable by name.
    content = (dest / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    _desc = ""
    try:
        m = re.search(r"^---\n(.*?)\n---", content, re.DOTALL)
        if m:
            import yaml
            _desc = str(yaml.safe_load(m.group(1)).get("description", ""))[:1024]
    except Exception:
        pass
    _files = {}
    for _sd in ("references", "templates", "scripts", "assets"):
        _sub = dest / _sd
        if _sub.exists() and _sub.is_dir():
            for _f in sorted(_sub.rglob("*")):
                if _f.is_file():
                    try:
                        _files[str(_f.relative_to(dest))] = _f.read_text(encoding="utf-8")
                    except Exception:
                        pass
    try:
        _rel = src.relative_to(lib)
        _cat = _rel.parts[0] if len(_rel.parts) >= 2 else ""
    except ValueError:
        _cat = ""
    if category:
        _cat = category
    _db_ok = _jpm_sync_skill(name, content, description=_desc,
                             files=json.dumps(_files), category=_cat,
                             file_path=str(dest / "SKILL.md"))

    action = "imported" if not already_local else "already_exists"
    msg = (f"Skill '{name}' imported to {dest}." if action == "imported"
           else f"Skill '{name}' already exists at {dest}.")
    if _db_ok:
        msg += " Registered in PG skills table."
    else:
        msg += " (PG unavailable — registered on disk only.)"
    return {"success": True, "action": action, "message": msg}


def _browse_library(category: str = None, name: str = None,
                    installed: bool = None) -> Dict[str, Any]:
    """List skills available in the bundled upstream library so the caller can
    decide which to import. Optionally filters by category, skill name, or
    installed status. Returns name, category, description, tags and whether the
    skill is already installed locally / in PG.

    This is the read-side companion to ``import``: browse upstream, then
    ``skill_manage(action='import', name=...)`` for the ones you want. No writes
    happen here.
    """
    try:
        from tools.skills_sync import _get_bundled_dir
    except Exception:
        return {"success": False,
                "error": "Bundled skills directory resolver unavailable."}

    lib = _get_bundled_dir()
    if lib is None or not lib.exists():
        return {"success": False,
                "error": f"Bundled skills directory not found: {lib}"}

    installed_set = set()
    try:
        from agent.skill_utils import get_all_skills_dirs
        for ext_dir in get_all_skills_dirs():
            if not ext_dir.exists():
                continue
            for md in ext_dir.rglob("SKILL.md"):
                if any(p.startswith(".") for p in md.parent.relative_to(ext_dir).parts):
                    continue
                installed_set.add(md.parent.name)
    except Exception:
        pass
    # DB is the primary store — a skill registered in PG (even DB-only, no disk
    # SKILL.md) counts as installed.
    if _JPM_AVAILABLE:
        try:
            from jpm.core._pg import sync_conn
            with sync_conn() as conn:
                for row in conn.fetchall("SELECT name FROM skills"):
                    if row["name"]:
                        installed_set.add(row["name"])
        except Exception:
            pass

    import yaml as _yaml
    rows = []
    for skill_md in sorted(lib.rglob("SKILL.md")):
        parent = skill_md.parent
        rel = parent.relative_to(lib)
        if any(p.endswith((".legacy-bak", ".bak", ".old", ".archived", ".backup"))
               or p.startswith(".") for p in rel.parts):
            continue
        cat = rel.parts[0] if len(rel.parts) >= 2 else ""
        sk_name = parent.name
        if category and cat != category:
            continue
        if name and name not in (sk_name, str(rel)):
            continue
        _desc, _tags = "", ""
        try:
            m = re.search(r"^---\n(.*?)\n---", skill_md.read_text(encoding="utf-8", errors="replace")[:4000], re.DOTALL)
            if m:
                _fm = _yaml.safe_load(m.group(1)) or {}
                _desc = str(_fm.get("description", ""))[:200]
                _tags = ", ".join(_fm.get("tags", []) or [])
        except Exception:
            pass
        is_installed = sk_name in installed_set
        if installed is not None and is_installed != installed:
            continue
        rows.append({
            "name": sk_name,
            "category": cat,
            "path": str(rel),
            "description": _desc,
            "tags": _tags,
            "installed": is_installed,
        })

    if not rows:
        return {"success": False,
                "error": f"No upstream skills found"
                         + (f" in category '{category}'" if category else "") + "."}

    return {"success": True, "count": len(rows), "skills": rows}


# =============================================================================
# Main entry point
# =============================================================================

# ContextVar bypass: set while replaying an already-approved staged skill write
# so skill_manage() does not re-gate (and re-stage) it.
import contextvars as _ctxvars
_skill_gate_bypass: "_ctxvars.ContextVar[bool]" = _ctxvars.ContextVar(
    "skill_gate_bypass", default=False
)
# ContextVar: when set, skill_manage writes to DB only (no disk writes).
# Used by the background self-improvement review fork so it doesn't produce
# "Patched SKILL.md" alerts or touch the filesystem.
_skill_db_only: "_ctxvars.ContextVar[bool]" = _ctxvars.ContextVar(
    "skill_db_only", default=False
)


def _apply_skill_write_gate(action, name, **payload_kwargs):
    """Evaluate the skill write gate. Returns a JSON tool-result string when the
    write should NOT proceed (blocked or staged), or None to perform the real
    write. Bypassed during approved-pending replay.
    """
    if action not in {"create", "edit", "patch", "delete", "write_file", "remove_file", "import"}:
        return None
    if _skill_gate_bypass.get():
        return None

    try:
        from tools import write_approval as wa
    except Exception:
        return None  # fail open

    decision = wa.evaluate_gate(wa.SKILLS)
    if decision.allow:
        return None
    if decision.blocked:
        return tool_error(decision.message, success=False)

    # stage — record the full skill_manage kwargs so approval can replay it.
    payload = {"action": action, "name": name}
    payload.update({k: v for k, v in payload_kwargs.items() if v is not None})
    gist = wa.skill_gist(
        action, name,
        content=payload_kwargs.get("content") or "",
        file_path=payload_kwargs.get("file_path") or "",
        old_string=payload_kwargs.get("old_string") or "",
        new_string=payload_kwargs.get("new_string") or "",
    )
    record = wa.stage_write(wa.SKILLS, payload, summary=gist, origin=wa.current_origin())
    return json.dumps(
        {"success": True, "staged": True, "pending_id": record["id"],
         "gist": gist, "message": decision.message},
        ensure_ascii=False,
    )


def apply_skill_pending(payload: Dict[str, Any]) -> str:
    """Replay a staged skill write, bypassing the gate. Returns the tool result
    JSON string. Called by the /skills approve handler.
    """
    token = _skill_gate_bypass.set(True)
    try:
        return skill_manage(
            action=payload.get("action", ""),
            name=payload.get("name", ""),
            content=payload.get("content"),
            category=payload.get("category"),
            file_path=payload.get("file_path"),
            file_content=payload.get("file_content"),
            old_string=payload.get("old_string"),
            new_string=payload.get("new_string"),
            replace_all=payload.get("replace_all", False),
            absorbed_into=payload.get("absorbed_into"),
        )
    finally:
        _skill_gate_bypass.reset(token)


def skill_manage(
    action: str,
    name: str,
    content: str = None,
    category: str = None,
    file_path: str = None,
    file_content: str = None,
    old_string: str = None,
    new_string: str = None,
    replace_all: bool = False,
    absorbed_into: str = None,
    installed: bool = None,
) -> str:
    """
    Manage user-created skills. Dispatches to the appropriate action handler.

    Returns JSON string with results.
    """
    preflight = _background_review_preflight(action, name)
    if preflight is not None:
        return json.dumps(preflight, ensure_ascii=False)

    # Approval gate: when on, stages the write for review (skills are too large
    # to review inline, so they always stage regardless of origin); when off
    # (default) passes straight through. The gate is bypassed when this call is
    # itself replaying an already-approved staged write (_skill_apply_pending).
    gate_result = _apply_skill_write_gate(
        action, name, content=content, category=category,
        file_path=file_path, file_content=file_content,
        old_string=old_string, new_string=new_string,
        replace_all=replace_all, absorbed_into=absorbed_into,
    )
    if gate_result is not None:
        return gate_result

    if action == "create":
        if not content:
            return tool_error("content is required for 'create'. Provide the full SKILL.md text (frontmatter + body).", success=False)
        result = _create_skill(name, content, category)

    elif action == "edit":
        if not content:
            return tool_error("content is required for 'edit'. Provide the full updated SKILL.md text.", success=False)
        result = _edit_skill(name, content)

    elif action == "patch":
        if not old_string:
            return tool_error("old_string is required for 'patch'. Provide the text to find.", success=False)
        if new_string is None:
            return tool_error("new_string is required for 'patch'. Use empty string to delete matched text.", success=False)
        result = _patch_skill(name, old_string, new_string, file_path, replace_all)

    elif action == "delete":
        result = _delete_skill(name, absorbed_into=absorbed_into)

    elif action == "write_file":
        if not file_path:
            return tool_error("file_path is required for 'write_file'. Example: 'references/api-guide.md'", success=False)
        if file_content is None:
            return tool_error("file_content is required for 'write_file'.", success=False)
        result = _write_file(name, file_path, file_content)

    elif action == "remove_file":
        if not file_path:
            return tool_error("file_path is required for 'remove_file'.", success=False)
        result = _remove_file(name, file_path)

    elif action == "import":
        result = _import_skill(name, category)

    elif action == "browse":
        result = _browse_library(category, name, installed)

    else:
        result = {"success": False, "error": f"Unknown action '{action}'. Use: create, edit, patch, delete, write_file, remove_file, import, browse"}

    if result.get("success"):
        try:
            from agent.prompt_builder import clear_skills_system_prompt_cache
            clear_skills_system_prompt_cache()
        except Exception:
            pass
        # Curator telemetry: bump patch_count on edit/patch/write_file (the actions
        # that mutate an existing skill's guidance), drop the record on delete.
        # Only mark a skill as agent-created when the background self-improvement
        # review fork creates it — foreground `skill_manage(create)` calls are
        # user-directed, and those skills belong to the user (the curator must
        # not touch them). Best-effort; telemetry failures never break the tool.
        try:
            from tools.skill_usage import bump_patch, forget, mark_agent_created
            from tools.skill_provenance import is_background_review
            if action == "create":
                if is_background_review():
                    mark_agent_created(name)
            elif action in {"patch", "edit", "write_file", "remove_file"}:
                bump_patch(name)
            elif action == "delete":
                if not result.get("_archived"):
                    forget(name)
        except Exception:
            pass

        # JPM PostgreSQL — sync full skill content to DB
        # DB is the primary read source (skill_view reads DB first).
        # For create/edit (full content), we write DB first, then disk.
        # For patch/write_file/remove_file (incremental), disk writes first,
        # then we read the full state from disk and sync to DB.
        # For delete, we archive in DB after disk delete.
        try:
            if action in ("create", "edit"):
                # DB was already written before the disk write (see above)
                pass
            elif action in ("patch", "write_file", "remove_file"):
                # Read full state from disk and sync to DB
                existing = _find_skill(name)
                if existing:
                    skill_dir = existing["path"]
                    skill_md = skill_dir / "SKILL.md"
                    if skill_md.exists():
                        _content = skill_md.read_text(encoding="utf-8")
                        _desc = ""
                        try:
                            _fm_end = re.search(r'\n---\s*\n', _content[3:])
                            if _fm_end:
                                _parsed = yaml.safe_load(_content[3:_fm_end.start() + 3])
                                _desc = str(_parsed.get("description", ""))[:1024]
                        except Exception:
                            pass
                        _files = {}
                        for _sd in ("references", "templates", "scripts", "assets"):
                            _sub = skill_dir / _sd
                            if _sub.exists() and _sub.is_dir():
                                for _f in sorted(_sub.rglob("*")):
                                    if _f.is_file():
                                        try:
                                            _rel = str(_f.relative_to(skill_dir))
                                            _files[_rel] = _f.read_text(encoding="utf-8")
                                        except Exception:
                                            pass
                        _cat = ""
                        try:
                            from agent.skill_utils import get_all_skills_dirs
                            for _sr in get_all_skills_dirs():
                                try:
                                    _rel = skill_dir.relative_to(_sr)
                                    if len(_rel.parts) >= 2:
                                        _cat = _rel.parts[0]
                                        break
                                except ValueError:
                                    continue
                        except Exception:
                            pass
                        _jpm_sync_skill(
                            name, _content,
                            description=_desc,
                            files=json.dumps(_files, ensure_ascii=False),
                            category=_cat,
                        )
            elif action == "delete":
                _jpm_remove_skill(name)
        except Exception:
            pass

    return json.dumps(result, ensure_ascii=False)


# =============================================================================
# OpenAI Function-Calling Schema
# =============================================================================

SKILL_MANAGE_SCHEMA = {
    "name": "skill_manage",
    "description": (
        "Manage your recipe book — create, update, and delete skills. Skills are "
        "procedural recipes that help you learn and adapt: they capture how to do "
        "recurring tasks so you don't fumble or re-derive from scratch, producing "
        "best results in fewer turns. Write a recipe when you solve a complex task, "
        "overcome errors, or get corrected — so the next run is one pass. "
        "Manage skills (create, update, delete). "
        f"New skills go to {display_joshaico_home()}/skills/; existing skills can be modified wherever they live.\n\n"
        "Actions: create (full SKILL.md + optional category), "
        "patch (old_string/new_string — preferred for fixes), "
        "edit (full SKILL.md rewrite — major overhauls only), "
        "delete, write_file, remove_file, "
        "import (copy an upstream library skill into ~/.joshaico/skills/ and "
        "register it in PG), browse (list upstream library skills with an "
        "installed flag; optional category/name/installed filters; read-only).\n\n"
        "On delete, pass `absorbed_into=<umbrella>` when you're merging this "
        "skill's content into another one, or `absorbed_into=\"\"` when you're "
        "pruning it with no forwarding target. This lets the curator tell "
        "consolidation from pruning without guessing, so downstream consumers "
        "(cron jobs that reference the old skill name, etc.) get updated "
        "correctly. The target you name in `absorbed_into` must already "
        "exist — create/patch the umbrella first, then delete.\n\n"
        "Create when: complex task succeeded (5+ calls), errors overcome, "
        "user-corrected approach worked, non-trivial workflow discovered, "
        "or user asks you to remember a procedure.\n"
        "Update when: instructions stale/wrong, OS-specific failures, "
        "missing steps or pitfalls found during use. "
        "If you used a skill and hit issues not covered by it, patch it immediately.\n\n"
        "PATCH DISCIPLINE (lean and accurate — the #1 rule):\n"
        "  - PATCH REPLACES, IT DOES NOT APPEND. When you add new info, REMOVE the "
        "old wording it supersedes in the same patch. Never layer new lines onto the "
        "tail while stale lines stay in the head — a skimming agent reads the head "
        "first and will act on the stale info. The body must read current top-to-bottom.\n"
        "  - Refresh the `description` on every patch that changes what the skill "
        "covers. The description is the index surface; if it lags the body, the "
        "agent's first skim is stale even when the body is right.\n"
        "  - A skill should get SHORTER or SHARPER over time, not longer. If a patch "
        "grows the body, look for a line it can replace or cut to stay lean.\n"
        "  - Split into a NEW skill only when the scope genuinely diverges into two "
        "unrelated capabilities — not because the body got long. Length is not the "
        "trigger; scope divergence is.\n\n"
        "After difficult/iterative tasks, offer to save as a skill. "
        "Skip for simple one-offs. Confirm with user before creating/deleting.\n\n"
        "Good skills: trigger conditions, numbered steps, pitfalls section, "
        "verification steps. Use skill_view() to see format examples.\n"
        "A skill is PROCEDURAL MEMORY: it records the delta that made this turn "
        "effective so the next turn is sharper. Capture what worked, what failed, "
        "and the fix. The test for every line: does this change what the agent "
        "would DO next time? If not, cut it.\n"
        "NEVER encode volatile implementation details in a skill: no line numbers, "
        "no hardcoded values, no function internals, no exact code snippets, no "
        "file paths into the codebase. These rot the moment the code changes. "
        "DO encode stable interfaces and durable facts: config keys, tool names, "
        "stable CLI flags, and the lesson itself. A skill says WHAT to do and WHY, "
        "not HOW the code currently works.\n\n"
        "MANDATORY frontmatter format (every create/edit). Copy this template:\n"
        "  ---\n"
        "  name: my-skill-name\n"
        "  description: \"Use when <trigger>. <one-line behavior>.\"\n"
        "  version: 1.0.0\n"
        "  author: Your Name\n"
        "  license: MIT\n"
        "  metadata:\n"
        "    joshaico:\n"
        "      tags: [two-word-tag, another-two-word]\n"
        "      related_skills: [peer-skill]\n"
        "  ---\n"
        "  <body: the procedure — at least one non-empty line>\n"
        "\n"
        "FRONTMATTER RULES — the validator runs on every create/edit/patch of SKILL.md:\n"
        "  - MUST start at byte 0 with `---` (no leading blank line or BOM).\n"
        "  - MUST close with a line containing only `---`.\n"
        "  - `name` required, ≤64 chars.\n"
        "  - `description` required, ≤1024 chars, and is the primary trigger — make it "
        "specific and pushy (~160 chars). Double-quote it whenever it contains a "
        "colon+space or any of `:{}[],&*#?|-<>=!%@\\`\"` — an unquoted colon+space is "
        "parsed as a nested mapping and the write is REJECTED.\n"
        "  - `tags` required — a non-empty list. Canonical spot is `metadata.joshaico.tags`; "
        "a top-level `tags:` list also works. Make each tag EXACTLY two words "
        "('fleet-mount', 'skill-authoring') — one word is too broad, 3+ words don't "
        "surface. Tags drive search; this is not optional.\n"
        "  - MUST have a non-empty body after the closing `---`.\n"
        "\n"
        "PER-ACTION PARAMS (pass only what the action uses):\n"
        "  - create      → name, content (full SKILL.md), category (optional — sets BOTH "
        "the disk subdir and the DB category; only meaningful here)\n"
        "  - patch       → name, old_string, new_string (optional: replace_all; file_path "
        "defaults to SKILL.md)\n"
        "  - edit        → name, content (the full rewritten SKILL.md)\n"
        "  - write_file  → name, file_path, file_content (path must be under "
        "references/ templates/ scripts/ assets/)\n"
        "  - remove_file → name, file_path\n"
        "  - delete      → name (optional absorbed_into)  |  browse → category/name/installed\n"
        "When updating an existing skill, refresh description and tags for new coverage and "
        "REPLACE stale claims — never leave outdated info in the body or frontmatter.\n\n"
        "Pinned skills are protected from deletion only — skill_manage(action='delete') "
        "will refuse with a message pointing the user to `joshaico curator unpin <name>`. "
        "Patches and edits go through on pinned skills so you can still improve them as "
        "pitfalls come up; pin only guards against irrecoverable loss."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "patch", "edit", "delete", "write_file", "remove_file", "import", "browse"],
                "description": "The action to perform."
            },
            "name": {
                "type": "string",
                "maxLength": 64,
                "description": (
                    "Skill name (lowercase, hyphens/underscores, max 64 chars). "
                    "Must match an existing skill for patch/edit/delete/write_file/remove_file."
                )
            },
            "content": {
                "type": "string",
                "maxLength": 100000,
                "description": (
                    "Full SKILL.md content (YAML frontmatter + markdown body). "
                    "Required for 'create' and 'edit'. For 'edit', read the skill "
                    "first with skill_view() and provide the complete updated text. "
                    "See the frontmatter template and rules in the tool description "
                    "above — copy it verbatim.\n\n"
                    "HARD LIMITS: content max 100,000 chars; frontmatter "
                    "`description` max 1024 chars. Exceeding either rejects the write. "
                    "`tags` must be a non-empty list (two-word tags recommended for "
                    "search relevance, not a hard rejection)."
                )
            },
            "old_string": {
                "type": "string",
                "description": (
                    "Text to find in the file (required for 'patch'). Must be unique "
                    "unless replace_all=true. Include enough surrounding context to "
                    "ensure uniqueness."
                )
            },
            "new_string": {
                "type": "string",
                "description": (
                    "Replacement text (required for 'patch'). Can be empty string "
                    "to delete the matched text."
                )
            },
            "replace_all": {
                "type": "boolean",
                "description": "For 'patch': replace all occurrences instead of requiring a unique match (default: false)."
            },
            "category": {
                "type": "string",
                "maxLength": 64,
                "description": (
                    "Optional category/domain for organizing the skill (e.g., 'devops', "
                    "'data-science', 'mlops'). Creates a subdirectory grouping. "
                    "Only used with 'create'."
                )
            },
            "file_path": {
                "type": "string",
                "description": (
                    "Path to a supporting file within the skill directory. "
                    "For 'write_file'/'remove_file': required, must be under references/, "
                    "templates/, scripts/, or assets/. "
                    "For 'patch': optional, defaults to SKILL.md if omitted."
                )
            },
            "file_content": {
                "type": "string",
                "description": "Content for the file. Required for 'write_file'."
            },
            "absorbed_into": {
                "type": "string",
                "description": (
                    "For 'delete' only — declares intent so the curator can "
                    "tell consolidation from pruning without guessing. "
                    "Pass the umbrella skill name when this skill's content "
                    "was merged into another (the target must already exist). "
                    "Pass an empty string when the skill is truly stale and "
                    "being pruned with no forwarding target. Omitting the arg "
                    "on delete is supported for backward compatibility but "
                    "downstream tooling (e.g. cron-job skill reference "
                    "rewriting) will have to guess at intent."
                )
            },
            "installed": {
                "type": "boolean",
                "description": (
                    "For 'browse' only — filter upstream library skills by "
                    "whether they are already installed (True = show installed, "
                    "False = show not-yet-installed, omit = show all)."
                )
            },
        },
        "required": ["action", "name"],
    },
}


