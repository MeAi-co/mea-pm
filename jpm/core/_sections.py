"""Skill section parser — split a SKILL.md body into ``##`` topic sections.

The skill catalog stores each skill as one row with the whole body in
``skills.content``. Retrieval is therefore whole-skill: to use one paragraph
the agent must load the entire body. This module gives the section index its
unit of granularity — a skill body is parsed on level-2 (``##``) headings into
an ordered list of sections, each of which is embedded and searched
independently (see ``skill_sections`` table + ``skill_choose(sections=True)``).

Design notes
  * Front matter (the leading ``---`` block) is stripped before parsing — it is
    already surfaced as the catalog card, so it is not a section.
  * The preamble before the first ``##`` heading becomes section ordinal 0 with
    an empty heading (kept so no prose is lost).
  * A body with no ``##`` headings yields a single section (the whole body).
  * Ordinals are stable per skill and re-derived on every write, so the
    ``UNIQUE (skill_id, ordinal)`` constraint lets a write replace sections
    wholesale without orphaning rows.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

# Leading YAML front matter: --- ... --- at the very start of the file.
_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n?", re.DOTALL)
# Level-2 ATX heading: "## Heading" (trailing #s and whitespace trimmed).
_H2_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)


def parse_sections(content: str) -> List[Dict[str, Any]]:
    """Split ``content`` into ``##`` sections.

    Returns a list of ``{"ordinal": int, "heading": str, "body": str}`` in
    document order. ``heading`` is the text after ``##`` (empty for the
    preamble). ``body`` is the section text with the heading line removed and
    surrounding whitespace stripped. Returns ``[]`` for empty content.
    """
    if not content or not content.strip():
        return []

    body = content
    fm = _FRONTMATTER_RE.match(content)
    if fm:
        body = content[fm.end():]

    matches = list(_H2_RE.finditer(body))
    sections: List[Dict[str, Any]] = []

    if not matches:
        text = body.strip()
        if text:
            sections.append({"ordinal": 0, "heading": "", "body": text})
        return sections

    preamble = body[: matches[0].start()].strip()
    ordinal = 0
    if preamble:
        sections.append({"ordinal": ordinal, "heading": "", "body": preamble})
        ordinal += 1

    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sec_body = body[start:end].strip()
        sections.append(
            {"ordinal": ordinal, "heading": m.group(1).strip(), "body": sec_body}
        )
        ordinal += 1

    return sections


def section_text(heading: str, body: str) -> str:
    """The text surface embedded for a section — heading + body.

    Kept in one place so the write path and any backfill produce the same
    vector (the drift class that bit the skills table: a sweep that embedded a
    different surface than the live write).
    """
    return "\n".join(p for p in (heading, body) if p and p.strip())[:8000]
