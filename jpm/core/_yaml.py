from ._pg import sync_conn
import typing
import logging

LOG = logging.getLogger(__name__)


def _build_yaml() -> typing.Optional[str]:
    """Build compact YAML context from all sections using a single DB connection."""
    lines = []

    try:
        with sync_conn() as conn:
            # Pulse
            pulse = conn.fetchone("SELECT status, summary FROM pulse ORDER BY created_at DESC LIMIT 1")
            if pulse:
                s = pulse["status"]
                summary = pulse["summary"]
                if s != "nominal" or summary:
                    lines.append(f"[Status] {s}" + (f": {summary[:100]}" if summary else ""))

            # Active focus
            active = conn.fetchone("SELECT focus, project, status FROM active ORDER BY updated_at DESC LIMIT 1")
            if active and active["focus"]:
                f = active["focus"]
                p = active["project"] or ""
                s = active["status"] or ""
                line = f"Focus: {f}"
                if p: line += f" [{p}]"
                if s: line += f" ({s})"
                lines.append(line)

            # Open loops (top 5 by priority)
            # Same alphabetical-sort defect as _provider.system_prompt_sections:
            # priority is TEXT, so `ORDER BY priority DESC` yields
            # medium > low > high > critical and buries critical loops.
            loops = conn.fetchall(
                "SELECT content, project, priority FROM loops WHERE resolved = 0 "
                "ORDER BY CASE priority "
                "WHEN 'critical' THEN 4 WHEN 'high' THEN 3 "
                "WHEN 'medium' THEN 2 ELSE 1 END DESC, created_at DESC LIMIT 5"
            )
            if loops:
                loop_lines = []
                for l in loops:
                    content = l["content"]
                    priority = l["priority"]
                    proj = l["project"] or ""
                    if content:
                        tag = f"[{priority.upper()}]" if priority != "medium" else ""
                        proj_tag = f"({proj})" if proj else ""
                        loop_lines.append(f"{tag} {content[:80]}{proj_tag}")
                if loop_lines:
                    lines.append("Loops: " + " | ".join(loop_lines[:5]))

            # Knowledge (top 3 by last_referenced)
            knowledge = conn.fetchall("SELECT entity_type, name, description FROM knowledge WHERE archived = 0 ORDER BY id DESC LIMIT 3")
            if knowledge:
                k_lines = []
                for k in knowledge:
                    t = k["entity_type"]
                    n = k["name"]
                    d = k["description"] or ""
                    if n:
                        kl = f"{n} ({t})"
                        if d:
                            kl += f": {d[:60]}"
                        k_lines.append(kl)
                if k_lines:
                    lines.append("Systems: " + " | ".join(k_lines[:3]))

            # Task context
            tasks = conn.fetchall("SELECT project_name, milestone, status FROM task_context ORDER BY updated_at DESC LIMIT 5")
            if tasks:
                t_lines = []
                for t in tasks:
                    pn = t["project_name"]
                    ms = t["milestone"] or ""
                    st = t["status"] or ""
                    if pn:
                        tl = pn
                        if ms:
                            tl += f" -> {ms}"
                        if st:
                            tl += f" [{st}]"
                        t_lines.append(tl)
                if t_lines:
                    lines.append("Projects: " + " | ".join(t_lines))
    except Exception:
        return None

    if not lines:
        return None

    return "\n".join(lines)


def _write_yaml(yaml_path: str, content: str) -> None:
    try:
        with open(yaml_path, "w") as f:
            f.write(content)
    except Exception as e:
        LOG.warning("jpm: failed to write YAML: %s", e)