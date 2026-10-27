import logging
import re
import json
import typing
import time
from contextvars import ContextVar
from datetime import datetime

from ._pg import sync_conn
from ._entity_query import _resolve_entity, _link_fact_entities
from ._cache import _get_cache

# ── Conversation-time stamping ──────────────────────────────────────────────
# When a backfill replays historical sessions, every knowledge/reflection row
# must carry the date of the CONVERSATION it was derived from — not the wall
# clock of the script run. Without this, 38 sessions spanning 11 real days all
# collapse onto one instant, which destroys temporal ordering and makes any
# date-relative or interval question unanswerable by construction.
#
# The backfill sets this per session; the live turn-end path leaves it unset
# and the column DEFAULT (CURRENT_TIMESTAMP) applies as before.
_CONVERSATION_TS: ContextVar[datetime | None] = ContextVar(
    "jpm_conversation_ts", default=None)


def set_conversation_ts(ts):
    """Pin the conversation timestamp for writes made in this context.

    Pass a datetime to stamp subsequent knowledge/reflection rows with it, or
    None to restore live behaviour (column DEFAULT).
    """
    return _CONVERSATION_TS.set(ts)


def reset_conversation_ts(token) -> None:
    """Undo a previous set_conversation_ts(token)."""
    try:
        _CONVERSATION_TS.reset(token)
    except Exception:
        pass


def _conversation_ts():
    """Current conversation timestamp, or None for live writes."""
    return _CONVERSATION_TS.get()

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def _mini_scalar(val: str):
    """Coerce one frontmatter scalar: inline list, quoted string, or bare."""
    v = val.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_mini_scalar(p) for p in inner.split(",") if p.strip()]
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def _mini_frontmatter(content: str) -> dict:
    """Dependency-free frontmatter parser, used when PyYAML is unavailable.

    The bench runtime interpreter ships WITHOUT PyYAML, so every
    `yaml.safe_load` frontmatter parse silently degraded to {} — skills
    imported with empty description/version/tags and names falling back to
    the directory name. This handles the subset SKILL.md frontmatter
    actually uses: top-level `key: value` scalars (quoted or bare), inline
    lists `[a, b]`, and nesting to any depth via indentation.

    Returns {} when there is no frontmatter block.
    """
    if not content or not content.startswith("---"):
        return {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", content, re.DOTALL)
    if not m:
        return {}
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for raw in m.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1] if stack else root
        if val == "":
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _mini_scalar(val)
    return root


def _load_frontmatter(content: str) -> dict:
    """Parse SKILL.md frontmatter, preferring PyYAML and falling back."""
    if not content:
        return {}
    if yaml is not None:
        try:
            m = re.search(r"\n---\s*\n", content[3:])
            if not m:
                return {}
            fm = yaml.safe_load(content[3:m.start() + 3])
            if isinstance(fm, dict):
                return fm
        except Exception:
            LOG.debug("yaml frontmatter parse failed; using fallback", exc_info=True)
    return _mini_frontmatter(content)

LOG = logging.getLogger("jpm.write")

# Trust adjustment constants
_HELPFUL_DELTA   =  0.05
_UNHELPFUL_DELTA = -0.10


# Valid pulse statuses per DB constraint: pulse_status_check
_VALID_PULSE_STATUSES = {"nominal", "blocked", "degraded", "idle"}


def _extract_skill_tags(content: str) -> str:
    """Parse tags from SKILL.md frontmatter into the DB's list-string format.

    Resolution order (backward compatible):
      1. metadata.hermes.tags        (canonical format)
      2. top-level tags:             (legacy flat format)

    Returns '' when no tags found, else a Python-list-style string like
    "['digest', 'reporting']" matching the existing skills.tags rows.
    """
    if not content:
        return ""
    try:
        fm = _load_frontmatter(content)
        if not isinstance(fm, dict):
            return ""
        tags = []
        metadata = fm.get("metadata")
        if isinstance(metadata, dict):
            for key in ("hermes",):
                meta = metadata.get(key)
                if isinstance(meta, dict):
                    tags = meta.get("tags") or []
                    if tags:
                        break
        if not tags:
            tags = fm.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in re.split(r"[,\[\]]+", tags) if t.strip()]
        clean = [str(t) for t in tags if str(t).strip()]
        return repr(clean) if clean else ""
    except Exception:
        LOG.debug("_extract_skill_tags parse failed", exc_info=True)
        return ""


def _write_pulse(status: str, summary: str, session_id: str = "",
                  confidence: typing.Optional[float] = None, source_message_id: typing.Optional[int] = None) -> bool:
    # Sanitize status to match DB constraint
    if status not in _VALID_PULSE_STATUSES:
        status = "degraded"
    try:
        with sync_conn() as conn:
            conn.execute(
                "INSERT INTO pulse (status, summary, session_id, confidence, source_message_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (status, summary, session_id,
                 confidence if confidence is not None else 0.95,
                 source_message_id)
            )
        return True
    except Exception as e:
        LOG.error("_write_pulse failed: %s", e, exc_info=True)
        return False


def _set_active(focus: str, project: str = "", status: str = "") -> bool:
    try:
        with sync_conn() as conn:
            now = datetime.now()
            conn.execute("DELETE FROM active")
            conn.execute("INSERT INTO active (focus, project, status, updated_at) VALUES (?, ?, ?, ?)",
                       (focus, project, status, now))
        return True
    except Exception as e:
        LOG.error("_set_active failed: %s", e, exc_info=True)
        return False


def _add_loop(content: str, project: str = "", priority: str = "medium") -> bool:
    try:
        with sync_conn() as conn:
            conn.execute("INSERT INTO loops (content, project, priority) VALUES (?, ?, ?)",
                       (content, project, priority))
        return True
    except Exception as e:
        LOG.error("_add_loop failed: %s", e, exc_info=True)
        return False


def _resolve_loop(content: str) -> bool:
    try:
        with sync_conn() as conn:
            conn.execute("UPDATE loops SET resolved = 1, resolved_at = ? WHERE content = ? AND resolved = 0",
                       (datetime.now(), content))
        return True
    except Exception as e:
        LOG.error("_resolve_loop failed: %s", e, exc_info=True)
        return False


def _extract_skill_version(content: str) -> str:
    """Parse the `version:` field from SKILL.md frontmatter into a string.

    Returns '' when missing/unparseable, so the DB version column lags
    gracefully rather than erroring. Matches the tag-parsing seam so the
    version column stays in sync with the frontmatter on every skill write.
    """
    if not content:
        return ""
    try:
        fm = _load_frontmatter(content)
        if not isinstance(fm, dict):
            return ""
        v = fm.get("version")
        return str(v).strip() if v is not None else ""
    except Exception:
        LOG.debug("_extract_skill_version parse failed", exc_info=True)
        return ""


def _derive_skill_tags(name: str, content: str, description: str = "") -> str:
    """Derive conservative tags from a skill when frontmatter has none.

    Only extracts terms that are clearly present in the skill's own content —
    never invents keywords. Sources, in priority order:
      1. The skill name (split on non-alphanumerics, drop stopwords).
      2. The frontmatter description's key nouns (words >= 4 chars, not stopwords).
      3. The frontmatter trigger/description lines (same filter).

    Returns a Python-list-style string like "['digest', 'reporting']" matching
    the existing skills.tags rows, or '' when nothing high-signal is found.
    """
    if not name and not content:
        return ""
    _STOP = {
        "the", "and", "for", "with", "from", "that", "this", "when", "what",
        "how", "why", "are", "you", "your", "will", "can", "use", "using",
        "used", "into", "onto", "about", "after", "before", "over", "under",
        "then", "than", "there", "their", "they", "them", "have", "has", "had",
        "not", "but", "all", "any", "each", "some", "such", "only", "also",
        "very", "just", "like", "make", "need", "want", "should",
        "would", "could", "might", "must", "may", "one", "two", "new", "old",
        "good", "bad", "big", "small", "more", "most", "less", "least",
    }
    seen = set()
    out = []

    def _add(word: str) -> None:
        w = word.strip().lower()
        if len(w) >= 4 and w not in _STOP and w not in seen:
            seen.add(w)
            out.append(w)

    # 1. Skill name — split on non-alphanumerics, keep meaningful tokens.
    for part in re.split(r"[^a-z0-9]+", name.lower()):
        _add(part)

    # 2. Description — pull key nouns from the description text.
    if description:
        for part in re.split(r"[^a-z0-9]+", description.lower()):
            _add(part)

    # 3. Frontmatter description/trigger lines from content (best-effort).
    if content:
        try:
            m = re.search(r"^---\s*\n(.*?)\n---", content, re.S | re.M)
            if m:
                fm = yaml.safe_load(m.group(1)) if yaml else None
                if isinstance(fm, dict):
                    for key in ("description", "trigger", "triggers"):
                        val = fm.get(key)
                        if isinstance(val, str):
                            for part in re.split(r"[^a-z0-9]+", val.lower()):
                                _add(part)
                        elif isinstance(val, list):
                            for item in val:
                                if isinstance(item, str):
                                    for part in re.split(r"[^a-z0-9]+", item.lower()):
                                        _add(part)
        except Exception:
            pass  # Best-effort; never fail the write on tag derivation.

    return repr(out) if out else ""


def _ensure_skill_frontmatter(name: str, content: str, description: str = "") -> str:
    """Guarantee a SKILL.md body carries valid frontmatter.

    The blind turn-end create path used to write a raw markdown body with no
    ``---`` block, so ``_extract_skill_tags`` returned '' and the writer fell
    back to ``_derive_skill_tags`` — which split the prose into ~20 junk words
    ('verifying','config','seems','effect',...). That is a poisoning vector: the
    agent later reads those as real tags. This synthesizes a minimal valid block
    (name/description/version/tags) when the body has none, so tags are always
    derived from a real frontmatter description — never from body prose.

    Returns the content unchanged when it already starts with a frontmatter
    block, or when yaml is unavailable (best-effort, never fail the write).
    """
    if not content or yaml is None:
        return content
    if re.match(r"^\s*---\s*\n", content):
        return content
    _desc = (description or "").strip() or f"Skill: {name}"
    # Derive 2-word tags from the name + description only (never body prose).
    _tags = _derive_skill_tags(name, "", _desc)
    _tag_list = _tags if _tags else "[]"
    fm = (
        "---\n"
        f"name: {name}\n"
        f"description: {json.dumps(_desc)}\n"
        "version: 1.0.0\n"
        "metadata:\n"
        "  hermes:\n"
        f"    tags: {_tag_list}\n"
        "---\n\n"
    )
    return fm + content.lstrip("\n")


def _upsert_skill(name: str, content: str, description: str = "", files: str = "{}", category: str = "", file_path: str = "", internal: typing.Optional[bool] = None) -> bool:
    """Store full skill content in the skills table (primary store)."""
    try:
        content = _ensure_skill_frontmatter(name, content, description)
        tags = _extract_skill_tags(content)
        if not tags:
            # Frontmatter had no tags — derive conservative ones from the
            # skill's own name/description so retrieval can still surface it.
            tags = _derive_skill_tags(name, content, description)
        version = _extract_skill_version(content)
        with sync_conn() as conn:
            now = datetime.now()
            # Preserve the stored `internal` flag when the caller doesn't
            # supply one. Every patch/edit/updater path calls this without
            # `internal`, and ON CONFLICT ... internal = excluded.internal
            # would otherwise reset it to the DEFAULT (false) on every content
            # edit — silently un-marking an internal skill. Only the create
            # path passes a real value; everything else must keep the stored
            # one. Same pattern as the file_path preservation in
            # _jpm_sync_skill.
            if internal is None:
                row = conn.fetchone(
                    "SELECT internal FROM skills WHERE name = ? LIMIT 1",
                    (name,),
                )
                internal = bool(row["internal"]) if row else False
            conn.execute("""
                INSERT INTO skills (name, category, description, content, tags, version, source, trust_level, updated_at, file_path, internal)
                VALUES (?, ?, ?, ?, ?, ?, 'local', 'builtin', ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    category = excluded.category,
                    description = excluded.description,
                    content = excluded.content,
                    tags = excluded.tags,
                    version = excluded.version,
                    source = excluded.source,
                    trust_level = excluded.trust_level,
                    updated_at = excluded.updated_at,
                    file_path = excluded.file_path,
                    internal = excluded.internal,
                    -- Re-embed on content change. The AFTER UPDATE trigger only
                    -- fires notify_embed_queue() when NEW.embedding IS NULL, and
                    -- the listener's sweep only heals NULL rows -- so an edit
                    -- that left the vector intact would silently keep a STALE
                    -- embedding forever (the exact drift found 2026-10-02: 134
                    -- of 178 skills carried August vectors). Clearing the three
                    -- embedding columns when the embedded text surface
                    -- (name/description/content, mirroring the listener's
                    -- text_builder) actually changes lets the trigger fire and
                    -- the listener re-embed within seconds.
                    embedding = CASE WHEN (skills.name, skills.description, skills.content)
                                       IS DISTINCT FROM
                                       (excluded.name, excluded.description, excluded.content)
                                     THEN NULL ELSE skills.embedding END,
                    embedding_model = CASE WHEN (skills.name, skills.description, skills.content)
                                             IS DISTINCT FROM
                                             (excluded.name, excluded.description, excluded.content)
                                           THEN NULL ELSE skills.embedding_model END,
                    embedding_updated_at = CASE WHEN (skills.name, skills.description, skills.content)
                                                  IS DISTINCT FROM
                                                  (excluded.name, excluded.description, excluded.content)
                                                THEN NULL ELSE skills.embedding_updated_at END
            """, (name, category, description[:1024], content, tags, version, now, file_path, internal))
        # ── Live embed + section index (async, non-blocking) ─────────
        # Fire-and-forget: never blocks the skill write. Mirrors the
        # knowledge path. The text surface MUST match the listener's
        # skills builder (name + description + content) so a re-embed
        # produces the same vector the sweep would.
        try:
            from jpm.core._embed_worker import enqueue
            from jpm.core._sections import parse_sections, section_text
            row = None
            with sync_conn() as conn:
                row = conn.fetchone("SELECT id FROM skills WHERE name = ? LIMIT 1", (name,))
            if row and row["id"] is not None:
                skill_id = int(row["id"])
                text = "\n".join(p for p in (name, description, content) if p and p.strip())
                enqueue("skills", skill_id, text)
                # ── Section index: re-derive this skill's `##` topics ──
                # DELETE + INSERT keeps the set exact (a removed heading must
                # not leave an orphan section). Each section is enqueued for
                # embedding through the same worker; the text surface is
                # heading + body (see _sections.section_text).
                sections = parse_sections(content)
                with sync_conn() as conn:
                    conn.execute(
                        "DELETE FROM skill_sections WHERE skill_id = ?", (skill_id,)
                    )
                    for sec in sections:
                        srow = conn.fetchone(
                            "INSERT INTO skill_sections (skill_id, ordinal, heading, body) "
                            "VALUES (?, ?, ?, ?) RETURNING id",
                            (skill_id, sec["ordinal"], sec["heading"], sec["body"]),
                        )
                        if srow and srow["id"] is not None:
                            enqueue(
                                "skill_sections",
                                int(srow["id"]),
                                section_text(sec["heading"], sec["body"]),
                            )
        except Exception:
            pass  # Never let embedding/sectioning break the write path.
        _get_cache().invalidate("knowledge_")
        return True
    except Exception as e:
        LOG.error("_upsert_skill failed: %s", e, exc_info=True)
        return False


def _derive_fingerprint(name: str, description: str) -> str:
    """Derive conservative alt-keywords for a knowledge entry when none given.

    Only extracts terms clearly present in the entry's own name/description —
    never invents. Sources, in priority order:
      1. The name field (split on non-alphanumerics, drop stopwords).
      2. Quoted phrases in the description (e.g. "catch up", "don't you remember").
      3. Key nouns from the description (words >= 4 chars, not stopwords).

    Returns a comma-separated string of alt-keywords, or '' when nothing
    high-signal is found. Callers may pass their own fingerprint to override.
    """
    if not name and not description:
        return ""
    _STOP = {
        "the", "and", "for", "with", "from", "that", "this", "when", "what",
        "how", "why", "are", "you", "your", "will", "can", "use", "using",
        "used", "into", "onto", "about", "after", "before", "over", "under",
        "then", "than", "there", "their", "they", "them", "have", "has", "had",
        "not", "but", "all", "any", "each", "some", "such", "only", "also",
        "very", "just", "like", "make", "need", "want", "should", "would",
        "could", "might", "must", "may", "one", "two", "new", "old", "good",
        "bad", "big", "small", "more", "most", "less", "least", "remember",
        "forget", "forgot", "talked", "talk", "about", "thing", "things",
    }
    seen = set()
    out = []

    def _add(word: str) -> None:
        w = word.strip().lower()
        if len(w) >= 4 and w not in _STOP and w not in seen:
            seen.add(w)
            out.append(w)

    # 1. Name field.
    for part in re.split(r"[^a-z0-9]+", name.lower()):
        _add(part)

    # 2. Quoted phrases in description — these are the natural-language
    #    triggers a user would actually say ("catch up", "don't you remember").
    #    Prefer double-quoted phrases (they handle internal apostrophes);
    #    fall back to single-quoted only when no internal apostrophe.
    if description:
        for m in re.finditer(r"\"([^\"]{3,})\"", description):
            phrase = m.group(1).strip().lower()
            if phrase and phrase not in seen:
                seen.add(phrase)
                out.append(phrase)
        for m in re.finditer(r"'([^']{3,})'", description):
            phrase = m.group(1).strip().lower()
            if phrase and phrase not in seen:
                seen.add(phrase)
                out.append(phrase)
        # 3. Key nouns from description.
        for part in re.split(r"[^a-z0-9]+", description.lower()):
            _add(part)

    return ", ".join(out) if out else ""


def _add_knowledge(entity_type: str, name: str, description: str, weightage: float = 0.5, fingerprint: str = "") -> bool:
    """Add knowledge entry with entity extraction and linking."""
    from ._profile import current_profile

    owner = current_profile()
    try:
        if not fingerprint:
            # No alt-keywords given — derive conservative ones from the entry's
            # own name/description so retrieval can still surface it.
            fingerprint = _derive_fingerprint(name, description)
        conv_ts = _conversation_ts()
        with sync_conn() as conn:
            if conv_ts is not None:
                # Backfill replay: stamp the CONVERSATION date, not now().
                conn.execute("""INSERT INTO knowledge (profile, entity_type, name, description, weightage, fingerprint, created_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?)
                               ON CONFLICT (profile, entity_type, name) DO UPDATE SET
                                   description = ?,
                                   weightage = ?,
                                   fingerprint = ?""",
                           (owner, entity_type, name, description, weightage, fingerprint, conv_ts,
                            description, weightage, fingerprint))
            else:
                conn.execute("""INSERT INTO knowledge (profile, entity_type, name, description, weightage, fingerprint)
                               VALUES (?, ?, ?, ?, ?, ?)
                               ON CONFLICT (profile, entity_type, name) DO UPDATE SET
                                   description = ?,
                                   weightage = ?,
                                   fingerprint = ?""",
                           (owner, entity_type, name, description, weightage, fingerprint,
                            description, weightage, fingerprint))
            row = conn.fetchone("SELECT id FROM knowledge WHERE profile = ? AND entity_type = ? AND name = ?",
                              (owner, entity_type, name))
            if row:
                fact_id = int(row["id"])
                # ── Entity linking (best-effort enrichment) ──────────
                # The knowledge row is already committed & durable above.
                # A failure here must NOT fail the whole write — only the
                # enrichment is lost.  Log and continue.
                try:
                    _link_fact_entities(conn, fact_id, name)
                    _link_fact_entities(conn, fact_id, description)
                except Exception as e:
                    LOG.warning("_add_knowledge entity-linking failed for id=%s (row already stored): %s",
                                fact_id, e, exc_info=True)
                # ── Live embed (async, non-blocking) ─────────────────
                # Fire-and-forget: never blocks the knowledge write on
                # Ollama.  Worker + watchdog reconciler guarantee freshness.
                try:
                    from jpm.core._embed_worker import enqueue
                    text = "\n".join(p for p in (name, description) if p and p.strip())
                    enqueue("knowledge", fact_id, text)
                except Exception:
                    pass  # Never let embedding break the write path.
        _get_cache().invalidate("knowledge_")
        return True
    except Exception as e:
        LOG.error("_add_knowledge failed: %s", e, exc_info=True)
        return False


def _add_reflection(insight: str, trigger: str = "", impact: int = 5, session_id: str = "") -> bool:
    try:
        conv_ts = _conversation_ts()
        with sync_conn() as conn:
            if conv_ts is not None:
                # reflections.created_at is DOUBLE PRECISION (epoch seconds),
                # NOT a timestamp — unlike knowledge.created_at. Passing a
                # datetime here raises asyncpg DataError and the row is lost.
                epoch = conv_ts.timestamp() if hasattr(conv_ts, "timestamp") else float(conv_ts)
                conn.execute("INSERT INTO reflections (session_id, trigger, insight, impact, created_at) VALUES (?, ?, ?, ?, ?)",
                           (session_id, trigger, insight, impact, epoch))
            else:
                conn.execute("INSERT INTO reflections (session_id, trigger, insight, impact) VALUES (?, ?, ?, ?)",
                           (session_id, trigger, insight, impact))
        return True
    except Exception as e:
        LOG.error("_add_reflection failed: %s", e, exc_info=True)
        return False


def _track_tool_use(tool_name: str) -> bool:
    try:
        with sync_conn() as conn:
            now = datetime.now()
            conn.execute("""
                INSERT INTO capabilities (tool_name, proficiency, last_used, use_count)
                VALUES (?, 'medium', ?, 1)
                ON CONFLICT(tool_name) DO UPDATE SET
                    last_used = ?,
                    use_count = capabilities.use_count + 1,
                    proficiency = CASE
                        WHEN capabilities.use_count >= 20 THEN 'high'
                        WHEN capabilities.use_count >= 5 THEN 'medium'
                        ELSE 'low'
                    END
            """, (tool_name, now, now))
        return True
    except Exception as e:
        LOG.error("_track_tool_use failed: %s", e, exc_info=True)
        return False


def _set_task_context(project_name: str, milestone: str = "", status: str = "") -> bool:
    try:
        with sync_conn() as conn:
            now = datetime.now()
            conn.execute("""
                INSERT INTO task_context (project_name, milestone, status, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (project_name) DO UPDATE SET
                    milestone = EXCLUDED.milestone,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at
            """, (project_name, milestone, status, now))
        return True
    except Exception as e:
        LOG.error("_set_task_context failed: %s", e, exc_info=True)
        return False


def _update_trust(fact_id: int, delta: float) -> int:
    """Adjust a fact's trust score. Returns the number of rows updated.

    Returns 0 when the fact_id doesn't exist (so callers can report a
    misleading-success instead of always returning 'ok'), and -1 on error.
    """
    try:
        from ._profile import knowledge_scope

        scope_sql, scope_params = knowledge_scope()
        with sync_conn() as conn:
            status = conn.execute(f"""
                UPDATE knowledge SET
                    weightage = GREATEST(0.0, LEAST(1.0, weightage + ?)),
                    helpful_count = CASE WHEN ?::float8 > 0 THEN helpful_count + 1 ELSE helpful_count END,
                    stale_count = CASE WHEN ?::float8 < 0 THEN stale_count + 1 ELSE stale_count END
                WHERE id = ? AND {scope_sql}
            """, (delta, delta, delta, fact_id, *scope_params))
            rowcount = conn.rowcount
        _get_cache().invalidate("knowledge_")
        return rowcount
    except Exception as e:
        LOG.error("_update_trust failed: %s", e, exc_info=True)
        return -1