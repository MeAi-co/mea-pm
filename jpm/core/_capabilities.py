"""Capabilities and task-context readers.

Canonical implementation for the `capabilities` and `task_context` fetch paths.
Wired into `_handle_jpm_fetch` in `_handlers.py` (replaces the inline SQL that
used to live there). Exported as public API via `jpm._get_capabilities` /
`jpm._get_task_context`.

ARCHIVED 2026-08-15 — the old `db_path` parameter was dead (ignored; these
always use `sync_conn()`). Dropped it and added filter + XML-render support so
the functions are actually useful and called.
"""

from typing import Any

from ._pg import sync_conn


def _escape_xml(text: str) -> str:
    # Markdown-safe: escape backticks and strip control chars.
    text = text.replace("`", "\\`")
    text = "".join(ch for ch in text if ch >= " " or ch in "\t\n\r")
    return text


def _get_capabilities(limit: int = 10, proficiency: str = "") -> list[dict]:
    """Return the most-used capabilities, optionally filtered by proficiency.

    Returns raw rows (dicts) for programmatic callers. The fetch handler
    renders these to XML via `_render_capabilities`.
    """
    try:
        with sync_conn() as conn:
            where = ""
            params: list[Any] = []
            if proficiency:
                where = "WHERE proficiency = ?"
                params.append(proficiency)
            params.append(limit)
            rows = conn.fetchall(
                f"SELECT tool_name, proficiency, use_count, last_used, last_used::text as ts "
                f"FROM capabilities {where} ORDER BY use_count DESC LIMIT ?",
                params,
            )
            return rows
    except Exception:
        return []


def _get_task_context(limit: int = 5, project_name: str = "", status: str = "") -> list[dict]:
    """Return recent task-context rows, optionally filtered by project/status.

    Returns raw rows (dicts) for programmatic callers. The fetch handler
    renders these to XML via `_render_task_context`.
    """
    try:
        with sync_conn() as conn:
            where = ""
            params: list[Any] = []
            if project_name:
                where = "WHERE project_name LIKE ?"
                params.append(f"%{project_name}%")
            if status:
                where_clause = "WHERE" if not where else "AND"
                where += f" {where_clause} status = ?"
                params.append(status)
            params.append(limit)
            rows = conn.fetchall(
                f"SELECT project_name, milestone, status, updated_at, updated_at::text as ts "
                f"FROM task_context {where} ORDER BY updated_at DESC LIMIT ?",
                params,
            )
            return rows
    except Exception:
        return []


def _render_capabilities(rows: list[dict], section: str = "capabilities") -> str:
    """Render capability rows to the markdown block the fetch handler returns."""
    if not rows:
        return f"**jpm {section}** · count 0"
    parts = [f"## jpm {section} · count {len(rows)}"]
    for r in rows:
        parts.append(
            f"- **tool:** `{_escape_xml(r['tool_name'])}` · proficiency {_escape_xml(r['proficiency'])} · uses {r['use_count']} · ts {r['ts']}"
        )
    return "\n".join(parts)


def _render_task_context(rows: list[dict], section: str = "task_context") -> str:
    """Render task-context rows to the markdown block the fetch handler returns."""
    if not rows:
        return f"**jpm {section}** · count 0"
    parts = [f"## jpm {section} · count {len(rows)}"]
    for r in rows:
        parts.append(
            f"- **project:** `{_escape_xml(r['project_name'])}` · milestone {_escape_xml(r['milestone'] or '')} · status {_escape_xml(r['status'] or '')} · ts {r['ts']}"
        )
    return "\n".join(parts)
