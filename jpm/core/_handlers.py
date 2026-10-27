from typing import Any
import typing
import os

from ._ensure import _ensure_db
from ._parse import parse_kv
from ._pg import sync_conn
from ._hybrid_search import hybrid_enabled
from ._write import (
    _write_pulse, _set_active, _add_loop, _resolve_loop,
    _add_knowledge, _add_reflection, _track_tool_use, _set_task_context,
)


def _handle_jpm_update(args: dict[str, Any], **kwargs) -> str:
    section = args.get("section", "")
    content = args.get("content", "")
    if not section or not content:
        return "**jpm error:** section and content are required"
    _ensure_db()
    data = parse_kv(content)
    if section == "pulse":
        ok = _write_pulse(data.get("status", "nominal"), data.get("summary", ""), data.get("session_id", ""))
    elif section == "active":
        ok = _set_active(data.get("focus", ""), data.get("project", ""), data.get("status", ""))
    elif section == "loops":
        ok = _add_loop(data.get("content", content), data.get("project", ""), data.get("priority", "medium"))
    elif section == "resolve_loop":
        ok = _resolve_loop(data.get("content", content))
    elif section == "knowledge":
        try:
            _weightage = float(data.get("weightage", 0.5))
        except (ValueError, TypeError):
            _weightage = 0.5
        ok = _add_knowledge(
            data.get("type", ""),
            data.get("name", ""),
            data.get("description", ""),
            _weightage,
            data.get("fingerprint", ""),
        )
    elif section == "reflection":
        try:
            _impact = int(data.get("impact", 5))
        except (ValueError, TypeError):
            _impact = 5
        ok = _add_reflection(data.get("insight", content), data.get("trigger", ""), _impact, data.get("session_id", ""))
    elif section == "capability":
        ok = _track_tool_use(data.get("tool", content))
    elif section == "task_context":
        ok = _set_task_context(data.get("project_name", ""), data.get("milestone", ""), data.get("status", ""))
    else:
        return f"**jpm error:** unknown section `{section}`"
    status = "ok" if ok else "error"
    return f"**jpm update** · section `{section}` · status {status}"


def _escape_xml(text: str) -> str:
    # Markdown-safe: escape backticks and strip control chars.
    text = text.replace("`", "\\`")
    text = "".join(ch for ch in text if ch >= " " or ch in "\t\n\r")
    return text


# ARCHIVED 2026-08-15 — dead code audit: _xml_tag has zero callers (only _escape_xml is used).
# Kept for reference per archive-don't-delete rule.
def _xml_tag(tag: str, content: str = "", attrs: typing.Optional[dict[str, str]] = None) -> str:
    attr_str = ""
    if attrs:
        for k, v in attrs.items():
            attr_str += f' {k}="{_escape_xml(str(v))}"'
    if content:
        return f"<{tag}{attr_str}>{_escape_xml(content)}</{tag}>"
    else:
        return f"<{tag}{attr_str}></{tag}>"


def _handle_jpm_fetch(args: dict[str, Any], **kwargs) -> str:
    section = args.get("section", "")
    limit = min(args.get("limit", 5), 50)
    filter_str = args.get("filter", "")
    if not section:
        return "**jpm error:** section is required"
    _ensure_db()
    filter_data = parse_kv(filter_str) if filter_str else {}
    try:
        with sync_conn() as conn:
            if section == "pulse":
                rows = conn.fetchall("SELECT status, summary, session_id, created_at, to_timestamp(created_at)::text as ts FROM pulse ORDER BY created_at DESC LIMIT ?", (limit,))
                if not rows:
                    return f"**jpm pulse** · count 0"
                parts = [f"## jpm pulse · count {len(rows)}"]
                for r in rows:
                    parts.append(f"- **status:** {r['status']} · ts {r['ts']} — {_escape_xml((r['summary'] or '')[:200])}")
                return "\n".join(parts)
            elif section == "active":
                rows = conn.fetchall("SELECT focus, project, status, updated_at, updated_at::text as ts FROM active ORDER BY updated_at DESC LIMIT ?", (limit,))
                if not rows:
                    return f"**jpm active** · count 0"
                parts = [f"## jpm active · count {len(rows)}"]
                for r in rows:
                    parts.append(f"- **focus:** {_escape_xml(r['focus'])} · project {_escape_xml(r['project'] or '')} · status {_escape_xml(r['status'] or '')} · ts {r['ts']}")
                return "\n".join(parts)
            elif section == "loops":
                where = "WHERE resolved = 0"
                params = []
                if filter_data.get("resolved") == "1":
                    where = "WHERE resolved = 1"
                if filter_data.get("priority"):
                    where += " AND priority = ?"
                    params.append(filter_data["priority"])
                if filter_data.get("project"):
                    where += " AND project = ?"
                    params.append(filter_data["project"])
                params.append(limit)
                rows = conn.fetchall(f"SELECT content, project, priority, resolved, created_at, created_at::text as ts FROM loops {where} ORDER BY priority DESC, created_at DESC LIMIT ?", params)
                if not rows:
                    return f"**jpm loops** · count 0"
                parts = [f"## jpm loops · count {len(rows)}"]
                for r in rows:
                    resolved = "true" if r["resolved"] else "false"
                    parts.append(f"- **priority:** {r['priority']} · project {_escape_xml(r['project'] or '')} · resolved {resolved} · ts {r['ts']} — {_escape_xml((r['content'] or '')[:120])}")
                return "\n".join(parts)
            elif section == "knowledge":
                from ._search import _search_knowledge
                from ._entity_query import _probe_entity
                search_query = filter_data.get("search")
                if search_query:
                    if hybrid_enabled():
                        from ._hybrid_search import hybrid_search_knowledge
                        results, _ = hybrid_search_knowledge(search_query, limit)
                    else:
                        results, _ = _search_knowledge(search_query, limit)
                    if not results:
                        return f"**jpm knowledge** · query `{search_query}` · count 0"
                    parts = [f"## jpm knowledge · query `{search_query}` · count {len(results)}"]
                    for r in results:
                        # _search_knowledge returns 'title' (aliased from 'name'), _probe_entity returns 'name'
                        name_val = r.get("name") or r.get("title", "")
                        desc = r.get("description", "")[:100]
                        content = f"{name_val} — {desc}" if desc else name_val
                        trust = r.get("weightage", 0.5)
                        parts.append(f"- **id {r.get('id', '')}** · type `{r.get('entity_type', 'general')}` · trust {trust:.2f} — {_escape_xml(content)}")
                    return "\n".join(parts)
                entity_query = filter_data.get("entity")
                if entity_query:
                    results = _probe_entity(entity_query, limit)
                    if not results:
                        return f"**jpm knowledge** · entity `{entity_query}` · count 0"
                    parts = [f"## jpm knowledge · entity `{entity_query}` · count {len(results)}"]
                    for r in results:
                        # _probe_entity returns 'name' directly, _search_knowledge returns 'title'
                        name_val = r.get("name") or r.get("title", "")
                        desc = r.get("description", "")[:100]
                        content = f"{name_val} — {desc}" if desc else name_val
                        trust = r.get("weightage", 0.5)
                        parts.append(f"- **id {r.get('id', '')}** · type `{r.get('entity_type', 'general')}` · trust {trust:.2f} — {_escape_xml(content)}")
                    return "\n".join(parts)
                from ._profile import knowledge_scope

                _scope_sql, _scope_params = knowledge_scope()
                where = f"WHERE archived = 0 AND {_scope_sql}"
                params = list(_scope_params)
                if filter_data.get("type"):
                    where += " AND entity_type = ?"
                    params.append(filter_data["type"])
                if filter_data.get("name"):
                    where += " AND name LIKE ?"
                    params.append(f"%{filter_data['name']}%")
                params.append(limit)
                rows = conn.fetchall(f"SELECT entity_type, name, description, last_referenced, last_referenced::text as ts FROM knowledge {where} ORDER BY id DESC LIMIT ?", params)
                if not rows:
                    return f"**jpm knowledge** · count 0"
                parts = [f"## jpm knowledge · count {len(rows)}"]
                for r in rows:
                    desc = r["description"][:100] if r["description"] else ""
                    content = f"{r['name']} — {desc}" if desc else r["name"]
                    parts.append(f"- **type:** `{r['entity_type']}` · ts {r['ts']} — {_escape_xml(content)}")
                return "\n".join(parts)
            elif section == "reflections":
                where = ""
                params = []
                if filter_data.get("session_id"):
                    where = "WHERE session_id = ?"
                    params.append(filter_data["session_id"])
                elif filter_data.get("impact"):
                    where = "WHERE impact >= ?"
                    params.append(int(filter_data["impact"]))
                elif filter_data.get("trigger"):
                    where = "WHERE trigger = ?"
                    params.append(filter_data["trigger"])
                params.append(limit)
                rows = conn.fetchall(f"SELECT id, insight, trigger, impact, session_id, created_at, to_timestamp(created_at)::text as ts FROM reflections {where} ORDER BY impact DESC, created_at DESC LIMIT ?", params)
                if not rows:
                    return f"**jpm reflections** · count 0"
                parts = [f"## jpm reflections · count {len(rows)}"]
                for r in rows:
                    parts.append(f"- **id {r['id']}** · impact {r['impact']} · trigger {_escape_xml(r['trigger'] or '')} · ts {r['ts']} — {_escape_xml((r['insight'] or '')[:150])}")
                return "\n".join(parts)
            elif section == "capabilities":
                from ._capabilities import _get_capabilities, _render_capabilities
                rows = _get_capabilities(limit, filter_data.get("proficiency", ""))
                return _render_capabilities(rows)
            elif section == "task_context":
                from ._capabilities import _get_task_context, _render_task_context
                rows = _get_task_context(limit, filter_data.get("project_name", ""), filter_data.get("status", ""))
                return _render_task_context(rows)
            return f"**jpm error:** unknown section `{_escape_xml(section)}`"
    except Exception as e:
        return f"**jpm error:** section `{_escape_xml(section)}` — {_escape_xml(str(e))}"