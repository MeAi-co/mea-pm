"""First-run skill-import nudge for the mea_pm plugin.

Two responsibilities, deliberately separated:

1. DETECTION (automatic, read-only). On ``initialize()`` we check whether the
   store has zero skills while the on-disk skills tree has SKILL.md files. If
   so we insert ONE high-priority loop telling the user an import is available.
   Detection never reads skill bodies, never writes to skill tables, and is
   wrapped so it can never break session init.

2. IMPORT (user-invoked only). ``import_skills_from_disk()`` is the ONLY code
   path that writes the skills table from disk. It is never called at boot and
   never scheduled in the background — the user must explicitly ask for it.

The split matters: an automatic import would silently change what the agent
knows mid-benchmark, which invalidates any A/B comparison. Detection is a
nudge; import is a decision.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any

from ._pg import sync_conn
from ._write import _upsert_skill, _add_loop, _resolve_loop, _load_frontmatter

LOG = logging.getLogger(__name__)

# The exact loop content used for the nudge. Kept as a module constant so the
# idempotency check, the insert, and the resolve call can never drift apart —
# _resolve_loop matches on exact content.
#
# The nudge is STRUCTURAL DRIFT, not a first-run notice: it persists for as
# long as the plugin is installed and the transfer is incomplete. A partial
# import does not deliver the full benefit of the plugin or the port, so the
# loop clears ONLY when the transfer is genuinely complete or the user
# explicitly declines. The body therefore carries the partial-benefit note so
# the agent surfaces it in its CTA.
NUDGE_LOOP_CONTENT = (
    "Skills available on disk but not fully imported: run the skill import to "
    "load them into memory (user-invoked, never automatic). A partial import "
    "does not deliver the full benefit of the plugin or the port — this clears "
    "only when the transfer is complete or you explicitly decline."
)

# Pre-2026-10-19 wording. Loops inserted under this string must be migrated to
# NUDGE_LOOP_CONTENT in the same pass, otherwise the idempotency check and
# _resolve_loop (both exact-content matches) miss the existing row and a
# duplicate nudge is created.
LEGACY_NUDGE_LOOP_CONTENT = (
    "Skills available on disk but not imported: run the skill import to load "
    "them into memory (user-invoked, never automatic)."
)

DECLINED_KEY = "skills_import_declined"

# Supporting-file directories inside a skill dir. These are the files that
# belong to a skill beyond its SKILL.md body.
SUPPORT_DIRS = ("references", "scripts", "templates", "assets")


def _skills_root() -> Path:
    """Resolve the on-disk skills tree for this runtime.

    JOSHAICO_HOME is set by main.py at startup; the skills tree lives beside
    it. Falls back to the bench_a home so a bare import still resolves.
    """
    home = os.environ.get("JOSHAICO_HOME", "")
    if home:
        return Path(home) / "skills"
    return Path.home() / ".hermes" / "skills"


def _count_disk_skills(root: Path | None = None) -> int:
    """Count SKILL.md files on disk. Existence check only — no file reads."""
    root = root or _skills_root()
    try:
        if not root.is_dir():
            return 0
        return sum(1 for _ in root.rglob("SKILL.md"))
    except Exception:
        return 0


def _count_disk_support_files(root: Path | None = None) -> int:
    """Count supporting files (references/scripts/templates/assets) on disk.

    Existence check only — no file reads. Files outside those four dirs
    (DESCRIPTION.md, README.md, LICENSE, .hub/*) are NOT skill payload and
    are deliberately excluded, so the completeness predicate compares like
    with like against the skill_files table.
    """
    root = root or _skills_root()
    try:
        if not root.is_dir():
            return 0
        n = 0
        for p in root.rglob("*"):
            if not p.is_file() or p.name == "SKILL.md":
                continue
            if any(part in SUPPORT_DIRS for part in p.parts):
                n += 1
        return n
    except Exception:
        return 0


def _count_db_skills() -> int:
    try:
        with sync_conn() as conn:
            row = conn.fetchone("SELECT count(*) AS n FROM skills")
            return int(row["n"]) if row else 0
    except Exception:
        return 0


def _count_db_skill_files() -> int:
    try:
        with sync_conn() as conn:
            row = conn.fetchone("SELECT count(*) AS n FROM skill_files")
            return int(row["n"]) if row else 0
    except Exception:
        return 0


def transfer_complete(root: Path | None = None) -> bool:
    """True only when disk and DB agree on BOTH skills and supporting files.

    This is the nudge's resolve predicate. A partial import (10 of 58 skills,
    or all skills but zero supporting files) leaves it False, so the loop
    stays open — the transfer has not delivered the full benefit of the
    plugin or the port yet.

    Compares counts, not identities: cheap, read-only, and sufficient to
    detect any shortfall. A DB count ABOVE the disk count is not a shortfall
    (extra DB-only skills are legitimate) — only a deficit blocks completion.
    """
    root = root or _skills_root()
    disk_skills = _count_disk_skills(root)
    disk_files = _count_disk_support_files(root)
    db_skills = _count_db_skills()
    db_files = _count_db_skill_files()
    return db_skills >= disk_skills and db_files >= disk_files


def _migrate_legacy_loop() -> None:
    """Rewrite any open loop carrying the pre-2026-10-19 wording in place.

    Idempotency and _resolve_loop both match on EXACT content, so changing
    NUDGE_LOOP_CONTENT without this would orphan the existing row and create
    a duplicate nudge on the next initialize(). UPDATE-in-place keeps the
    loop id stable.
    """
    try:
        with sync_conn() as conn:
            conn.execute(
                "UPDATE loops SET content = ? WHERE content = ? AND resolved = 0",
                (NUDGE_LOOP_CONTENT, LEGACY_NUDGE_LOOP_CONTENT),
            )
    except Exception as e:
        LOG.error("_migrate_legacy_loop failed: %s", e, exc_info=True)


def _declined() -> bool:
    try:
        with sync_conn() as conn:
            row = conn.fetchone(
                "SELECT value FROM state_meta WHERE key = ? LIMIT 1", (DECLINED_KEY,)
            )
            return bool(row and str(row["value"]).strip() in ("1", "true", "True", "yes"))
    except Exception:
        return False


def _set_declined() -> bool:
    try:
        with sync_conn() as conn:
            conn.execute(
                "INSERT INTO state_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (DECLINED_KEY, "1"),
            )
        return True
    except Exception as e:
        LOG.error("_set_declined failed: %s", e, exc_info=True)
        return False


def detect_and_nudge() -> bool:
    """Insert the import nudge loop if the transfer is incomplete.

    Returns True when a loop was inserted, False otherwise. Never raises —
    a detection failure must not break session init.

    The gate is COMPLETENESS, not "any skills exist". A partial import (10 of
    58 skills, or all skills but zero supporting files) must NOT silence the
    nudge: the transfer has not delivered the full benefit of the plugin or
    the port, so the drift is still live.
    """
    try:
        if _declined():
            return False
        if _count_disk_skills() <= 0:
            return False
        # Migrate any pre-2026-10-19 row BEFORE the idempotency check, so the
        # exact-content match below sees it and no duplicate is created.
        _migrate_legacy_loop()
        if transfer_complete():
            return False
        # Idempotent: an unresolved copy of this exact loop already exists.
        with sync_conn() as conn:
            row = conn.fetchone(
                "SELECT id FROM loops WHERE resolved = 0 AND content = ? LIMIT 1",
                (NUDGE_LOOP_CONTENT,),
            )
            if row:
                return False
        return bool(_add_loop(NUDGE_LOOP_CONTENT, priority="high"))
    except Exception as e:
        LOG.error("detect_and_nudge failed: %s", e, exc_info=True)
        return False


def decline_import() -> bool:
    """User declined the import: resolve the nudge and remember the decision."""
    try:
        _resolve_loop(NUDGE_LOOP_CONTENT)
        return _set_declined()
    except Exception as e:
        LOG.error("decline_import failed: %s", e, exc_info=True)
        return False


# ── Frontmatter parsing ────────────────────────────────────────────────────
# Delegated to _write._load_frontmatter, which prefers PyYAML and falls back
# to a dependency-free parser. The bench runtime interpreter ships WITHOUT
# PyYAML, so a local yaml-only parser here silently produced {} for every
# skill — names fell back to directory names and description/version/tags
# were all lost on import.

def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse YAML frontmatter into a dict. Returns {} when absent/invalid."""
    try:
        return _load_frontmatter(text) or {}
    except Exception:
        return {}


def _tags_to_str(tags: Any) -> str:
    """Normalise frontmatter tags (list or str) into the DB's text form."""
    if isinstance(tags, (list, tuple)):
        return ",".join(str(t).strip() for t in tags if str(t).strip())
    if isinstance(tags, str):
        return tags.strip()
    return ""


def _write_skill_files(name: str, files: dict[str, str]) -> int:
    """Replace all skill_files rows for a skill. Returns rows written.

    The plugin had NO writer for skill_files anywhere (grep -rn "skill_files"
    --include=*.py returned nothing), so the table could never be populated
    and the completeness predicate could never pass. DELETE + INSERT keeps
    the set exact — a removed supporting file must not leave an orphan row.
    """
    if not files:
        return 0
    try:
        with sync_conn() as conn:
            row = conn.fetchone("SELECT id FROM skills WHERE name = ? LIMIT 1", (name,))
            if not row or row["id"] is None:
                return 0
            skill_id = int(row["id"])
            conn.execute("DELETE FROM skill_files WHERE skill_id = ?", (skill_id,))
            n = 0
            for fp, content in files.items():
                conn.execute(
                    "INSERT INTO skill_files (skill_id, file_path, content) "
                    "VALUES (?, ?, ?)",
                    (skill_id, fp, content),
                )
                n += 1
            return n
    except Exception as e:
        LOG.error("_write_skill_files failed for %s: %s", name, e, exc_info=True)
        return 0


def _collect_support_files(skill_dir: Path) -> dict[str, str]:
    """Read a skill's supporting files into {relative_path: content}.

    Only references/|scripts/|templates/|assets/ are collected — those are
    the dirs skill_files is meant to hold. Paths are stored relative to the
    skill dir, matching how the workflow tool resolves script_path.
    """
    out: dict[str, str] = {}
    try:
        for sub in SUPPORT_DIRS:
            d = skill_dir / sub
            if not d.is_dir():
                continue
            for p in sorted(d.rglob("*")):
                if not p.is_file():
                    continue
                try:
                    out[str(p.relative_to(skill_dir))] = p.read_text(
                        encoding="utf-8", errors="replace"
                    )
                except Exception as e:
                    LOG.warning("support file unreadable %s: %s", p, e)
    except Exception as e:
        LOG.warning("_collect_support_files failed for %s: %s", skill_dir, e)
    return out


def import_skills_from_disk(root: Path | None = None) -> dict[str, Any]:
    """Import every SKILL.md under the skills tree into the skills table.

    USER-INVOKED ONLY. This is the sole writer of skill rows from disk.

    Also imports each skill's supporting files into skill_files — without
    that, the completeness predicate can never pass and the nudge can never
    resolve.

    Returns a report dict: {imported, skipped, failed, errors, total,
    files_imported, complete}.
    """
    root = root or _skills_root()
    report: dict[str, Any] = {
        "imported": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
        "total": 0,
        "files_imported": 0,
        "complete": False,
    }
    try:
        if not root.is_dir():
            report["errors"].append(f"skills root not found: {root}")
            return report
        paths = sorted(root.rglob("SKILL.md"))
        report["total"] = len(paths)
        for path in paths:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                fm = _parse_frontmatter(content)
                name = str(fm.get("name") or path.parent.name).strip()
                if not name:
                    report["failed"] += 1
                    report["errors"].append(f"{path}: no name")
                    continue
                description = str(fm.get("description") or "").strip()
                # Category = the skill's parent directory (skills/<category>/<name>/).
                category = path.parent.parent.name if path.parent.parent else ""
                if category == "skills":
                    category = ""
                ok = _upsert_skill(
                    name=name,
                    content=content,
                    description=description,
                    category=category,
                    file_path=str(path),
                )
                if ok:
                    report["imported"] += 1
                    report["files_imported"] += _write_skill_files(
                        name, _collect_support_files(path.parent)
                    )
                else:
                    report["failed"] += 1
                    report["errors"].append(f"{path}: upsert returned False")
            except Exception as e:
                report["failed"] += 1
                report["errors"].append(f"{path}: {e}")
        # Resolve ONLY on genuine completion. A partial import leaves the
        # loop open — the transfer has not delivered the full benefit yet.
        report["complete"] = transfer_complete(root)
        if report["complete"]:
            _resolve_loop(NUDGE_LOOP_CONTENT)
        return report
    except Exception as e:
        LOG.error("import_skills_from_disk failed: %s", e, exc_info=True)
        report["errors"].append(str(e))
        return report
