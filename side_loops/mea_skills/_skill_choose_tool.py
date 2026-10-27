#!/usr/bin/env python3
"""skill_choose — browse the skill catalog's front matter before loading.

A catalog browser with an optional semantic shortlist. With no arguments it
lists every active skill's metadata (name, description, category, tags) so the
agent can see what exists and pick what fits THIS turn. Pass ``query`` and it
ranks the catalog by embedding similarity instead, returning the top matches
with Google-style matched-text snippets. Either way the agent then calls
skill_view to load the full SKILL.md body.

Why a browser, not a picker:
  The old skill_choose read the deterministic picker's ranked stash and
  returned "candidates" with tiers/scores — a picker giving its opinion about
  what the agent *should* load. That's redundant and paternalizing. The agent
  is the decision-maker. skill_choose exists so the agent can browse the
  catalog cheaply (front matter only, no full bodies) and decide for itself.
  Loading the full body is the expensive part and happens only via skill_view.

Mechanism
  Enumerates the same skill source as skills_list (DB skills table first,
  filesystem scan fallback) and returns front matter: name, category,
  description, tags. Pass ``name`` to inspect a single skill's full front
  matter in detail. Pass ``names`` for a shortlist. Pass ``query`` for a
  semantic shortlist (HNSW cosine over skills.embedding, the index already
  exists). Read-only — never consumes or ranks anything destructively.

Snippets
  The card description is a *snippet*, not the whole description. When a query
  (or the shortlist ``q``) is present, the snippet is the window of the
  description around the matched phrase, rendered Google-style:
  "….xxxxx yyyyy xxxxx ….". When nothing matches (e.g. plain browsing), the
  snippet falls back to the leading slice. This keeps cards scannable without
  loading full bodies.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _catalog_rows() -> List[Dict[str, Any]]:
    """Enumerate the skill catalog (name/description/category/tags) the same
    way skills_list does — DB-backed when available, filesystem fallback."""
    from _skills_tool import _skills_from_db, _find_all_skills, _sort_skills

    db_skills = _skills_from_db()  # name/description/category only (no tags)
    if db_skills:
        return _sort_skills(db_skills)
    # Filesystem scan carries tags via _find_all_skills? It returns name/
    # description/category — tags not parsed there. Enrich with a filesystem
    # read of frontmatter when available.
    return _sort_skills(_find_all_skills())


_DESC_PREVIEW_CHARS = 200  # leading slice used when no query match exists
_DESC_SNIPPET_CHARS = 90   # matched window size for query-driven snippets
_ELLIPSIS = "…"


def _frontmatter_map() -> Dict[str, Dict[str, Any]]:
    """Parse front matter for EVERY skill on disk in a single tree walk.

    The old per-skill helper walked the entire skills tree once per skill,
    making skill_choose O(N^2): 175 skills x ~136-file walks = ~4.4s wall time
    just to render the catalog. One walk keyed by skill dir name is O(N).
    Returns {skill-dir-name: {"tags": [...], "description": "..."}}; skills not
    on disk (DB-only) are simply absent and fall back to the DB description.
    """
    from _skills_tool import SKILLS_DIR, _parse_tags, _parse_frontmatter
    from agent.skill_utils import iter_skill_index_files

    out: Dict[str, Dict[str, Any]] = {}
    if not SKILLS_DIR.exists():
        return out
    for skill_md in iter_skill_index_files(SKILLS_DIR, "SKILL.md"):
        # skill_md is .../<skill-name>/SKILL.md — the name is the parent dir,
        # not the file stem (which is just "SKILL").
        name = skill_md.parent.name
        if name in out:
            continue  # first occurrence wins, matching old first-match behavior
        try:
            frontmatter, _ = _parse_frontmatter(
                skill_md.read_text(encoding="utf-8")[:4000]
            )
        except Exception:
            continue
        joshaico_meta = frontmatter.get("metadata", {}) or {}
        joshaico = joshaico_meta.get("joshaico", {}) if isinstance(joshaico_meta, dict) else {}
        tags = _parse_tags(joshaico.get("tags") or frontmatter.get("tags", ""))
        out[name] = {
            "tags": tags,
            "description": frontmatter.get("description", "") or "",
        }
    return out


def _make_snippet(query: str, text: str, width: int = _DESC_SNIPPET_CHARS) -> str:
    """Return a Google-style matched window of ``text`` around ``query``.

    Strategy: try the full query first (case-insensitive); if it isn't present
    (common — the query is usually natural language, the description isn't),
    fall back to the longest token of length >= 4 that appears in the text.
    Center the window on the match, add leading/trailing ellipsis when text was
    trimmed. No match -> leading slice. Always returns a non-empty string for
    non-empty text. Bounded to ``width`` chars so cards stay scannable.
    """
    text = (text or "").strip()
    if not text:
        return ""
    if len(text) <= width:
        return text

    q = (query or "").strip().lower()
    low = text.lower()
    pos = -1
    match_len = 0
    if q:
        pos = low.find(q)
        match_len = len(q)
        if pos < 0:
            # longest token that actually appears, so we anchor on something real
            tokens = sorted(
                {t for t in _tokenize(q) if len(t) >= 4},
                key=len,
                reverse=True,
            )
            for t in tokens:
                p = low.find(t)
                if p >= 0:
                    pos, match_len = p, len(t)
                    break

    if pos < 0:
        return text[:width].rstrip() + _ELLIPSIS

    # Center the window on the midpoint of the match.
    mid = pos + match_len // 2
    start = max(0, mid - width // 2)
    end = min(len(text), start + width)
    start = max(0, end - width)  # shift left if we hit the tail
    window = text[start:end].strip()

    prefix = _ELLIPSIS if start > 0 else ""
    suffix = _ELLIPSIS if end < len(text) else ""
    return f"{prefix}{window}{suffix}"


def _tokenize(s: str) -> List[str]:
    import re
    return [t for t in re.split(r"[^a-z0-9]+", s) if t]


def _vector_rank(query: str, limit: int) -> List[Tuple[str, float]]:
    """Rank skills by cosine distance to ``query`` via the HNSW index.

    Returns [(name, distance), ...] best-first, deduped by name (the table can
    hold duplicate rows for one skill; keep the closest). Raises nothing —
    returns [] on any failure so the caller can fall back to browse order.
    """
    try:
        from jpm.core._ollama import embed_query
        from jpm.core._pg import sync_conn

        qv = embed_query(query)
        if not qv:
            return []
        vec_literal = "[" + ",".join(f"{v:.6f}" for v in qv) + "]"
        with sync_conn() as conn:
            rows = conn.fetchall(
                f"""
                SELECT name, dist FROM (
                    SELECT DISTINCT ON (name) name,
                           embedding <=> '{vec_literal}'::vector AS dist
                    FROM skills
                    WHERE state = 'active' AND embedding IS NOT NULL
                    ORDER BY name, dist ASC
                ) t
                ORDER BY dist ASC
                LIMIT {int(limit)}
                """
            )
        return [(r["name"], float(r["dist"])) for r in rows]
    except Exception as e:
        logger.warning("skill_choose: vector rank failed, falling back to browse: %s", e)
        return []


def _section_rank(query: str, limit: int) -> List[Dict[str, Any]]:
    """Rank skill *sections* by cosine distance to ``query`` via HNSW.

    Returns [{skill, heading, ordinal, body, dist}, ...] best-first across ALL
    skills — the cherry-pick view: the matching topic from each of several
    skills, not whole bodies. Returns [] on any failure so the caller falls
    back to whole-skill ranking.
    """
    try:
        from jpm.core._ollama import embed_query
        from jpm.core._pg import sync_conn

        qv = embed_query(query)
        if not qv:
            return []
        vec_literal = "[" + ",".join(f"{v:.6f}" for v in qv) + "]"
        with sync_conn() as conn:
            rows = conn.fetchall(
                f"""
                SELECT s.name AS skill, sec.heading, sec.ordinal, sec.body,
                       sec.embedding <=> '{vec_literal}'::vector AS dist
                FROM skill_sections sec
                JOIN skills s ON s.id = sec.skill_id
                WHERE s.state = 'active' AND sec.embedding IS NOT NULL
                ORDER BY dist ASC
                LIMIT {int(limit)}
                """
            )
        return [
            {
                "skill": r["skill"],
                "heading": r["heading"],
                "ordinal": r["ordinal"],
                "body": r["body"],
                "dist": float(r["dist"]),
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("skill_choose: section rank failed, falling back: %s", e)
        return []


def _load_topics(specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Load full bodies for a list of {skill, section} specs — the cherry-pick
    loader. One call pulls N topics from M skills. ``section`` is optional: when
    omitted the whole skill body is returned. Returns {topics: [...], count: N,
    loaded: N, errors: [...]}. Each topic carries skill/heading/body.
    """
    from _skills_tool import _skill_body_from_db, _apply_section_filter
    from jpm.core._sections import parse_sections

    topics: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for spec in specs or []:
        if not isinstance(spec, dict):
            errors.append({"spec": spec, "error": "spec must be {skill, section}"})
            continue
        skill = str(spec.get("skill") or spec.get("name") or "").strip()
        section = str(spec.get("section") or spec.get("heading") or "").strip()
        if not skill:
            errors.append({"spec": spec, "error": "missing 'skill'"})
            continue
        body, _files, _desc = _skill_body_from_db(skill)
        if not body:
            errors.append({"skill": skill, "error": "skill not found"})
            continue
        if section:
            res = _apply_section_filter({"content": body}, section)
            if res.get("section_not_found"):
                errors.append({
                    "skill": skill, "section": section,
                    "error": "section not found",
                    "available_sections": res.get("available_sections", []),
                })
                continue
            topics.append({
                "skill": skill,
                "heading": res.get("section_heading") or "(preamble)",
                "body": res.get("content") or "",
            })
        else:
            topics.append({"skill": skill, "heading": "(full body)", "body": body})
    return {"topics": topics, "count": len(topics), "loaded": len(topics), "errors": errors}


def skill_choose(
    name: Optional[str] = None,
    names: Optional[List[str]] = None,
    query: Optional[str] = None,
    sections: bool = False,
    load: Optional[List[Dict[str, Any]]] = None,
    task_id: Optional[str] = None,
) -> str:
    """Browse the skill catalog's front matter. Returns name/category/
    description (and tags when available) for every skill — or a single skill's
    front matter when ``name`` is passed, or a shortlist's front matter when
    ``names`` (a list) is passed. Pass ``query`` for a semantic shortlist ranked
    by embedding similarity. Read-only; does not load bodies.
    Use skill_view(name) to load a chosen skill's full content."""
    from tools.registry import tool_result, tool_error

    # --- Cherry-pick load path ---------------------------------------------
    # load=[{skill, section}, ...] pulls full topic bodies across multiple
    # skills in ONE call — the second half of the skill_choose loop. Bypasses
    # the catalog read entirely (it reads bodies directly).
    if load:
        payload = _load_topics(load)
        n = payload["loaded"]
        payload["note"] = (
            f"Loaded {n} topic(s) into context. "
            + (f"{len(payload['errors'])} spec(s) failed — see errors." if payload["errors"] else "")
        )
        return tool_result(payload)

    try:
        rows = _catalog_rows()
    except Exception as e:  # pragma: no cover - defensive
        logger.exception("skill_choose: failed to enumerate catalog")
        return tool_error(f"skill_choose: could not read catalog: {e}")

    if not rows:
        return tool_result(
            {"skills": [], "count": 0,
             "note": "No skills in the catalog."}
        )

    # Optional shortlist detail (case-insensitive substring match on a list).
    wanted_names = [n.strip().lower() for n in (names or []) if n and n.strip()]
    if wanted_names:
        rows = [
            r for r in rows
            if any(w in str(r.get("name") or "").lower() for w in wanted_names)
        ]
        if not rows:
            return tool_error(
                f"skill_choose: no skills matching {names!r} in the catalog. "
                "Call skill_choose() with no args to browse all skills."
            )

    # Optional single-skill detail (case-insensitive substring match).
    wanted = (name or "").strip().lower()
    if wanted:
        rows = [r for r in rows if wanted in str(r.get("name") or "").lower()]
        if not rows:
            return tool_error(
                f"skill_choose: no skill named {name!r} in the catalog. "
                "Call skill_choose() with no args to browse all skills."
            )

    # --- Semantic shortlist path -------------------------------------------
    # Rank by embedding cosine, then narrow the browse rows to the shortlist.
    # Preserves the ranked order (browse rows are name-sorted, ranking is not).
    q_text = (query or "").strip()

    # --- Section (topic) path ----------------------------------------------
    # sections=True + query ranks `##` topics across ALL skills and returns the
    # matching sections themselves — the cherry-pick view. Falls through to the
    # whole-skill path when the section index is empty (not yet backfilled).
    if sections and q_text:
        secs = _section_rank(q_text, limit=_SECTION_LIMIT)
        if secs:
            out = []
            truncated_any = False
            for i, s in enumerate(secs):
                body = s["body"]
                # The top matches are returned IN FULL — the whole point of the
                # cherry-pick view is to hand the model the chapter it needs, and
                # the follow-up load call has historically never fired. Only the
                # tail of the list is previewed, and each preview is flagged so
                # the model can see exactly which bodies are cut.
                if i < _SECTION_FULL_TOP or len(body) <= _SECTION_BODY_CHARS:
                    entry = {
                        "skill": s["skill"],
                        "heading": s["heading"] or "(preamble)",
                        "ordinal": s["ordinal"],
                        "body": body,
                        "score": round(1.0 - s["dist"], 3),
                    }
                else:
                    truncated_any = True
                    entry = {
                        "skill": s["skill"],
                        "heading": s["heading"] or "(preamble)",
                        "ordinal": s["ordinal"],
                        "body": body[:_SECTION_BODY_CHARS].rstrip() + _ELLIPSIS,
                        "score": round(1.0 - s["dist"], 3),
                        "truncated": True,
                        "full_chars": len(body),
                    }
                out.append(entry)
            note = (
                f"Top {len(out)} skill sections for {q_text!r} (semantic, "
                f"across all skills). The top {min(_SECTION_FULL_TOP, len(out))} "
                "are loaded IN FULL — use them directly."
            )
            if truncated_any:
                note += (
                    " Sections marked `truncated: true` are previews only; "
                    "load any of them in full with "
                    "skill_choose(load=[{skill: '<skill>', section: '<heading>'}])."
                )
            return tool_result({
                "sections": out,
                "count": len(out),
                "note": note,
            })

    ranked: List[Tuple[str, float]] = []
    if q_text:
        ranked = _vector_rank(q_text, limit=_VECTOR_LIMIT)
        if ranked:
            order = {n.lower(): i for i, (n, _) in enumerate(ranked)}
            by_name = {str(r.get("name") or "").lower(): r for r in rows}
            rows = [
                by_name[n] for n, _ in ranked if n.lower() in by_name
            ] or rows

    # Build front-matter cards. Each card shows tags and a *snippet* of the long
    # description: a matched window when a query is present, otherwise a leading
    # slice. Front matter is parsed once for all skills, not re-walked per skill.
    fm_map = _frontmatter_map()
    skills: List[Dict[str, Any]] = []
    for r in rows:
        entry = {
            "name": r.get("name"),
            "category": r.get("category"),
            "description": r.get("description"),
        }
        from _skills_tool import _apply_role_fields
        _apply_role_fields(entry, r.get("role_tags") or "")
        fm = fm_map.get(str(r.get("name") or ""))
        # Prefer the on-disk frontmatter description (full-length source); fall
        # back to the DB description. Truncate/snippet UNIFORMLY either way —
        # skills with no on-disk match (DB-only, or disk dir name != DB name,
        # e.g. book_*) would otherwise dump their entire description into the
        # card and blow up the payload.
        full = ""
        if fm:
            full = str(fm.get("description") or "").strip()
        if not full:
            full = str(entry.get("description") or "").strip()
        if full:
            if q_text:
                entry["description"] = _make_snippet(q_text, full)
            else:
                entry["description"] = (
                    full[:_DESC_PREVIEW_CHARS].rstrip() + _ELLIPSIS
                    if len(full) > _DESC_PREVIEW_CHARS else full
                )
        if fm and fm.get("tags"):
            entry["tags"] = fm.get("tags")
        skills.append(entry)

    payload: Dict[str, Any] = {"skills": skills, "count": len(skills)}
    if q_text:
        payload["note"] = (
            f"Semantic shortlist for {q_text!r} (top {len(skills)} by embedding "
            "similarity, snippets show the matched region). skill_view(name=...) "
            "to load a full body. Omit query to browse the whole catalog."
        )
    else:
        payload["note"] = (
            "Skill Catalog browser - Browse Your Skill Library, then skill_view(name='<name>') to load the "
            "full body. Pick Multiple that fits this turn. Pass query='...' for a semantic top-N shortlist. Or Create New ones at turn end"
        )
    return tool_result(payload)


_VECTOR_LIMIT = 12  # default shortlist size for query= runs
_SECTION_LIMIT = 12  # default section count for sections=True runs
_SECTION_FULL_TOP = 3  # top-N sections returned IN FULL (no preview cap)
_SECTION_BODY_CHARS = 600  # per-section body preview cap for the tail of the list


# --- JSON schema (auto-injected into the model's tool list) ---
SKILL_CHOOSE_SCHEMA = {
    "type": "object",
    "description": (
        "Your skill library is a REFERENCE SECTION LIBRARY — a catalog of "
        "procedural recipes (skills) split into `##` topics (chapters). Treat "
        "it as the shelf you consult whenever you are in doubt: before "
        "answering from memory, before concluding a procedure doesn't exist, "
        "before improvising a workflow. Loading the right chapters makes your "
        "turn HIGH-SIGNAL and grounded instead of random guesswork.\n\n"
        "THREE MODES:\n"
        "1. DISCOVER — `query='<what this turn is about>'` ranks the whole "
        "catalog by embedding similarity and returns the top matches with "
        "snippets. Add `sections=true` to rank `##` TOPICS across ALL skills "
        "instead of whole-skill cards — the cherry-pick view, best when you "
        "need one chapter from several skills or a slice of a long skill.\n"
        "2. LOAD — `load=[{skill, section}, ...]` pulls the FULL bodies of "
        "those topics into context in ONE call, across multiple skills. Omit "
        "`section` to load a whole skill. This is the second half of the loop: "
        "discover with query+sections, then load the picks here. Returns "
        "{topics, loaded, errors}; a bad section returns available_sections.\n"
        "3. BROWSE — no args lists the full catalog (front matter only, cheap); "
        "`name=` inspects one skill's front matter; `names=[...]` a shortlist.\n\n"
        "Use `skill_view(name)` only when you want a whole skill body. Prefer "
        "skill_choose(load=) to cherry-pick chapters — it is cheaper and keeps "
        "the turn focused."
    ),
    "properties": {
        "name": {
            "type": "string",
            "description": (
                "Optional. A single skill name to inspect its front matter in "
                "detail. Omit to browse the full catalog."
            ),
        },
        "names": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Optional. A shortlist of skill names (up to 5) to inspect "
                "their front matter in detail. Use this to quick-browse a few "
                "candidates before loading the fits with skill_view."
            ),
        },
        "query": {
            "type": "string",
            "description": (
                "Optional. What this turn is about, in natural language. "
                "Ranks the catalog by embedding similarity and returns the top "
                "matches with matched-text snippets. Use this whenever the task "
                "intent is clear — it is the fast path to the right skill. Omit "
                "to browse everything."
            ),
        },
        "sections": {
            "type": "boolean",
            "description": (
                "Optional. With query=, rank `##` topics across ALL skills and "
                "return the matching sections themselves (heading + body) "
                "instead of whole-skill cards — the cherry-pick view. The top "
                "matches are returned IN FULL; any section marked "
                "`truncated: true` is a preview only and can be loaded in full "
                "with skill_choose(load=[{skill, section}]). Use when you need "
                "one topic from several skills, or a slice of a long skill."
            ),
        },
        "load": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string", "description": "Skill name."},
                    "section": {"type": "string", "description": "Optional `##` topic heading (case-insensitive substring). Omit for the whole body."},
                },
                "required": ["skill"],
            },
            "description": (
                "Optional. Cherry-pick loader: a list of {skill, section} specs "
                "whose FULL topic bodies are loaded into context in ONE call — "
                "across multiple skills. This is the second half of the loop: "
                "browse with query=+sections=true, then load the picks here. "
                "Omit section to load a whole skill body. Returns {topics, "
                "loaded, errors}."
            ),
        },
    },
    "required": [],
}


