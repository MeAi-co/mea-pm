import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ._paths import _get_joshaico_home
from ._pg import sync_conn, apply_schema, shutdown as _pg_shutdown
from ._cache import _LRUCache, _get_cache
from ._ensure import _ensure_db
from ._entities import _extract_entities
from ._read import _get_latest_pulse
from ._search import _search_knowledge
from ._hybrid_search import hybrid_enabled, hybrid_search_knowledge
from ._entity_query import _probe_entity, _related_entities, _reason_entities


_LOCAL_TZ = timezone(timedelta(hours=4))  # Asia/Dubai (UTC+4), no DST

# Core tables that back the agent's own memory. Destructive statements
# (DROP/TRUNCATE/DELETE/ALTER/REINDEX) against these are HARD-BLOCKED so a
# single wrong jpm query can't wipe the agent's knowledge, sessions, or
# messages. Destructive ops on any other (non-core) table still require an
# explicit confirm=true before they run.
_CORE_TABLES = {
    "knowledge", "messages", "sessions", "reflections", "patterns",
    "skills", "active", "loops", "capabilities", "task_context",
    "tool_calls", "gateway_events", "state", "_recent_sync",
    "llm_calls", "oracle_diagnostics", "oracle_log",
}

# Statement keywords that can destroy data. Anything starting with one of
# these is treated as destructive and routed through the guard below.
_DESTRUCTIVE_KEYWORDS = ("DROP", "TRUNCATE", "DELETE", "ALTER", "REINDEX")


# ARCHIVED 2026-08-15 — dead code audit: _local_tz() has zero callers (only _LOCAL_TZ constant is used).
# Kept for reference per archive-don't-delete rule.
def _local_tz():
    return _LOCAL_TZ
from ._write import (
    _write_pulse, _add_knowledge, _add_loop, _add_reflection,
    _set_active, _resolve_loop, _track_tool_use, _set_task_context,
    _update_trust,
)
from ._schemas import JPM_SCHEMA
from ._handlers import _handle_jpm_update, _handle_jpm_fetch


def _quote_ident(s: str) -> str:
    """Quote a PG identifier safely (double-quote, escape embedded quotes).

    Split on '.' so schema-qualified names (public.tab) quote each part.
    """
    return ".".join('"' + part.replace('"', '""') + '"' for part in str(s).split("."))


# ── Cell value truncation for query output ────────────────────────────────
# query returns a row list; long cell values are truncated by default so a
# SELECT * over a table with content/blob columns can't blow up the agent's
# context. Every cut value gets an explicit '…[+N chars]' marker so the
# caller ALWAYS knows it was truncated and can fetch the full row via the
# `row` action (table= + id=) or the `get` action. Pass truncate=0/off to
# return full cell values in one pass when the result set is known to be
# small.
_DEFAULT_VAL_LEN = 100


def _truncate_cell(v, max_len=_DEFAULT_VAL_LEN):
    """Truncate a long cell value, marking explicitly when cut.

    None renders as "" for display. When the string exceeds max_len it is
    cut to the first max_len chars with a trailing '+N chars' marker so
    the agent knows the value was truncated and how much is hidden.
    max_len=0 / falsy returns the value in full (no truncation).
    """
    if v is None:
        return ""
    s = str(v)
    if not max_len or len(s) <= max_len:
        return s
    return s[:max_len] + f"…[+{len(s) - max_len} chars]"


# ── User-table prefix (user_<name>) ────────────────────────────────────────
# User-created tables (via create_table or raw SQL) live under a `user_` name
# prefix so they're visually separated from core jpm tables in the public
# schema. Agents keep using the BARE name (charter_fleet, bliss_calendar, ...)
# and _rewrite_user_table_refs() transparently resolves those bare references
# to the physical user_<name> so no agent query or script needs to know about
# the prefix.

_USER_PREFIX = "user_"


def _load_user_table_map(conn):
    """Map bare user-table name -> physical user_<name> from information_schema.

    Returns {} when there are no user tables yet. Only matches tables that
    carry the `user_` prefix, so core tables are never affected.
    """
    rows = conn.fetchall(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name LIKE 'user\\_%' "
        "ORDER BY table_name"
    )
    m = {}
    for r in rows:
        t = str(r.get("table_name") or "")
        if t.startswith(_USER_PREFIX) and len(t) > len(_USER_PREFIX):
            m[t[len(_USER_PREFIX):]] = t
    return m


def _user_phys_name(conn, table):
    """Return the physical (possibly prefixed) name for a user-table reference."""
    if not table:
        return table
    # Already prefixed or schema-qualified? leave as-is.
    base = str(table).split(".")[-1]
    if base.startswith(_USER_PREFIX):
        return table
    m = _load_user_table_map(conn)
    if base in m:
        # Preserve any schema qualifier the caller used.
        if "." in str(table):
            return str(table).rsplit(".", 1)[0] + "." + m[base]
        return m[base]
    return table


def _rewrite_user_table_refs(sql, user_map):
    """Rewrite bare user-table refs (charter_fleet) -> user_charter_fleet.

    Walks the SQL token-by-token, skipping single-quoted string literals and
    double-quoted identifiers, and replaces whole-word bare references that
    match a known user-table bare name. Already-prefixed refs are untouched
    (word boundaries handle that naturally: `user_charter_fleet` has no \b
    between `user_` and `charter_fleet`). Returns the rewritten SQL.
    """
    if not user_map:
        return sql
    bare_names = sorted(user_map, key=len, reverse=True)
    # Match a whole-word bare name. Left boundary forbids a preceding word char
    # OR a '.' (so schema-qualified refs like `yachting.charter_fleet` are NOT
    # rewritten — only unqualified bare table names are). Right boundary is a
    # word boundary so `user_charter_fleet` / `my_charter_fleet` are untouched.
    pat = re.compile(r"(?<![\w.])(?:" + "|".join(re.escape(b) for b in bare_names) + r")\b")
    out = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i : j + 1])
            i = j + 1
        elif ch == '"':
            j = i + 1
            while j < n:
                if sql[j] == '"':
                    if j + 1 < n and sql[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i : j + 1])
            i = j + 1
        else:
            j = i
            while j < n and sql[j] not in "'\"":
                j += 1
            chunk = sql[i:j]
            out.append(pat.sub(lambda m: user_map[m.group(0)], chunk))
            i = j
    return "".join(out)


# ── Companion imports (role-gated — only Mia loads tone/mood) ──────
try:
    from ._paths import _get_joshaico_home
    _cfg_path = Path(_get_joshaico_home()) / "config.yaml"
    if _cfg_path.exists():
        import yaml as _yaml
        with open(_cfg_path) as _f:
            _jpm_cfg = _yaml.safe_load(_f) or {}
        _agent_cfg = _jpm_cfg.get("agent", {})
        if _agent_cfg.get("role") == "companion":
            from jpm.ext.agent_tone import detect_tone as _detect_tone
            from jpm.ext.agent_state import _set_state as _set_mia, ensure_state_tables as _ensure_mia
        else:
            _detect_tone = None
            _set_mia = None
            _ensure_mia = None
    else:
        _detect_tone = None
        _set_mia = None
        _ensure_mia = None
except Exception:
    _detect_tone = None
    _set_mia = None
    _ensure_mia = None

LOG = logging.getLogger(__name__)

# Track which sessions have received first-turn YAML context injection
_INJECTED_SESSIONS: set[str] = set()


class JPMemoryProvider:
    """MemoryProvider-compatible wrapper for JPM v4.

    Implements the MemoryProvider ABC so JPM can be set as the active
    memory backend via memory.provider: jpm in config.yaml.

    Provides the unified jpm() tool — a PgAdmin-lite: fetch/update/add/get/
    search/probe/related/reason/contradict/list/remove/helpful/unhelpful for
    memory + facts, and tables/schema/query/row/create_table/rename_table/index
    for direct PG schema inspection and SQL.
    """

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._cache: _LRUCache | None = None
        self._session_id: str = ""
        self._chat_type: str = ""

    @property
    def name(self) -> str:
        return "jpm"

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id
        self._chat_type = kwargs.get("chat_type", "")
        _ensure_db()
        if _ensure_mia is not None:
            _ensure_mia()
        self._cache = _get_cache()
        # First-run skill-import nudge. Detection ONLY — read-only existence
        # checks, one loop insert at most. The import itself is user-invoked
        # (see _skill_import.import_skills_from_disk) and is never called
        # here: an automatic import would change what the agent knows
        # mid-session and invalidate any A/B comparison. Wrapped so a
        # detection failure can never break session init.
        try:
            from ._skill_import import detect_and_nudge
            detect_and_nudge()
        except Exception:
            pass
        LOG.info("jpm: initialized for session %s (chat_type=%s)", session_id, self._chat_type)

    def system_prompt_sections(self) -> dict:
        """Return ordered markdown sections for the system prompt.

        Sections (in canonical order): identity, soul, user_pref, memory,
        rules, breadcrumbs, state. Only weightage >= 0.70 is injected in
        full; 0.21-0.69 becomes a breadcrumb pointer; <=0.20 is skipped.

        Returns a dict of {section_name: markdown_string}. Empty sections
        are omitted. The caller (patches/system_prompt.py) assembles these
        in the final order with Directives slotted between user_pref and
        memory.
        """
        try:
            with sync_conn() as conn:
                sections: dict[str, str] = {}
                breadcrumbs: list[str] = []

                def _fetch(entity_type: str) -> list[str]:
                    """Full-injection entries (weightage >= 0.70) as markdown bullets."""
                    is_group = self._chat_type in ("group", "supergroup")
                    if is_group:
                        rows = conn.fetchall(
                            "SELECT name, description FROM knowledge "
                            "WHERE entity_type = ? AND archived = 0 AND weightage >= 0.70 "
                            "ORDER BY entity_type ASC, weightage DESC, id DESC LIMIT 100",
                            (entity_type,)
                        )
                    else:
                        rows = conn.fetchall(
                            "SELECT name, description FROM knowledge "
                            "WHERE entity_type = ? AND archived = 0 AND weightage >= 0.70 "
                            "AND description NOT LIKE '[GROUP RULE]%' "
                            "ORDER BY entity_type ASC, weightage DESC, id DESC LIMIT 50",
                            (entity_type,)
                        )
                    out = []
                    for row in rows:
                        name = (row["name"] or "").strip()
                        desc = (row["description"] or "").strip()
                        if not desc:
                            continue
                        # Avoid "Name: Name: ..." duplication when the stored
                        # description already leads with the entry name.
                        if name and desc.startswith(name):
                            desc = desc[len(name):].lstrip(": -")
                        out.append(f"- **{name}:** {desc}")
                    return out

                def _breadcrumb(entity_type: str) -> None:
                    """Count medium-weight entries (0.21-0.69) and emit one pointer."""
                    is_group = self._chat_type in ("group", "supergroup")
                    if is_group:
                        row = conn.fetchone(
                            "SELECT COUNT(*) FROM knowledge "
                            "WHERE entity_type = ? AND archived = 0 "
                            "AND weightage > 0.20 AND weightage < 0.70  LIMIT 50",
                            (entity_type,)
                        )
                    else:
                        row = conn.fetchone(
                            "SELECT COUNT(*) FROM knowledge "
                            "WHERE entity_type = ? AND archived = 0 "
                            "AND weightage > 0.20 AND weightage < 0.70 "
                            "AND description NOT LIKE '[GROUP RULE]%' LIMIT 50",
                            (entity_type,)
                        )
                    count = row["count"] if row else 0
                    if count > 0:
                        breadcrumbs.append(
                            f"- *{entity_type}:* available via "
                            f'jpm(action="fetch", section="{entity_type}")'
                        )

                # ── Identity ────────────────────────────────────────────
                id_lines = _fetch("identity")
                if id_lines:
                    sections["identity"] = "\n".join(id_lines)

                # ── Soul (persona / voice) ────────────────────────────────
                soul_lines = _fetch("soul")
                if soul_lines:
                    sections["soul"] = "\n".join(soul_lines)

                # ── User preferences ─────────────────────────────────────
                up_lines = _fetch("user_pref")
                _breadcrumb("user_pref")
                if up_lines:
                    sections["user_pref"] = "\n".join(up_lines)

                # ── Memory entries ───────────────────────────────────────
                mem_lines = _fetch("memory_entry")
                _breadcrumb("memory_entry")
                if mem_lines:
                    sections["memory"] = "\n".join(mem_lines)

                # ── Rules ─────────────────────────────────────────────────
                rule_lines = _fetch("rule")
                _breadcrumb("rule")
                if rule_lines:
                    sections["rules"] = "\n".join(rule_lines)

                # ── Breadcrumbs ──────────────────────────────────────────
                if breadcrumbs:
                    sections["breadcrumbs"] = "\n".join(breadcrumbs)

                # ── State (pulse / tone / focus / loops) ─────────────────
                state_lines: list[str] = []

                pulse = conn.fetchone("SELECT status, summary, confidence, source_message_id, session_id FROM pulse ORDER BY created_at DESC LIMIT 1")
                if pulse and pulse["status"] != "nominal":
                    conf = pulse["confidence"] if pulse["confidence"] is not None else 0.95
                    src = pulse["session_id"] or ""
                    line = f"- **Status:** {pulse['status']}"
                    if pulse["summary"]:
                        line += f" — {pulse['summary'][:80]}"
                    line += f" (confidence={conf:.2f})"
                    if src:
                        line += f" [session: {src[:20]}]"
                    state_lines.append(line)
                    if conf < 0.7:
                        state_lines.append("  > ⚠️ please confirm this state is still accurate")

                try:
                    state_row = conn.fetchone("SELECT mood, energy, headspace, updated_at FROM state ORDER BY updated_at DESC LIMIT 1")
                    if state_row and state_row["mood"] and state_row["mood"] != "neutral":
                        tone = state_row["mood"]
                        style_row = conn.fetchone(
                            "SELECT response_style, escalation_risk, indicators FROM emotional_tones WHERE name = ?",
                            (tone,)
                        )
                        if style_row:
                            style = style_row["response_style"] or ""
                            risk = style_row["escalation_risk"] or 0.0
                            line = f"- **User tone:** {tone}"
                            if risk >= 0.5:
                                line += f" (escalation risk {risk:.1f})"
                            if style:
                                line += f" — {style}"
                            state_lines.append(line)
                except Exception:
                    pass

                active = conn.fetchone("SELECT focus, project, status FROM active ORDER BY updated_at DESC LIMIT 1")
                if active and active["focus"]:
                    f = active["focus"]
                    p = active["project"] or ""
                    s = active["status"] or ""
                    line = f"- **Focus:** {f}"
                    if p: line += f" [{p}]"
                    if s: line += f" ({s})"
                    state_lines.append(line)

                # Priority is a TEXT column with a CHECK constraint
                # (low|medium|high|critical), so a plain `ORDER BY priority DESC`
                # sorts ALPHABETICALLY: medium > low > high > critical. That
                # silently buried `critical` loops below `low` ones and dropped
                # them out of the LIMIT 3 window entirely. Rank explicitly.
                loops = conn.fetchall(
                    "SELECT content, priority FROM loops WHERE resolved = 0 "
                    "ORDER BY CASE priority "
                    "WHEN 'critical' THEN 4 WHEN 'high' THEN 3 "
                    "WHEN 'medium' THEN 2 ELSE 1 END DESC, created_at DESC LIMIT 3"
                )
                for l in loops:
                    tag = f"[{l['priority'].upper()}]"
                    state_lines.append(f"- {tag} {l['content'][:80]}")

                if state_lines:
                    sections["state"] = "\n".join(state_lines)

                return sections
        except Exception:
            return {}

    def system_prompt_block(self) -> str:
        """Combined markdown context block (backward-compatible wrapper).

        Assembles the sections from system_prompt_sections() in canonical
        order. The patch layer (patches/system_prompt.py) prefers the
        per-section dict so it can interleave Directives correctly; this
        string form is kept for any caller that just wants one blob.
        """
        sections = self.system_prompt_sections()
        if not sections:
            return (
                "# JPM VAULT Memory\n"
                "jpm is a powerful database tool: use action='query' (arbitrary SQL), 'schema',\n"
                "'tables', 'row' to inspect the PG database directly — no credentials needed."
            )

        order = ["identity", "soul", "user_pref", "memory", "rules", "breadcrumbs", "state"]
        parts = []
        for key in order:
            if key in sections:
                parts.append(sections[key])
        body = "\n\n".join(parts)
        tools = (
            "Tools: vault (fetch/update/add/search/probe/reason/helpful/unhelpful/query/schema/tables/row)"
        )
        return f"{body}{tools}"

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Recall relevant context for the upcoming turn.

        Strategy: VECTOR-FIRST (best recall) — hybrid_search_knowledge runs
        pgvector nearest-neighbour recall as the primary path, with FTS only
        as a crutch when embeddings/Ollama are unavailable. Then entity probes
        to pull
        facts linked to capitalized names in the query. Results are
        deduped by fact id, filtered to the most relevant entity types,
        and ranked so the strongest match surfaces first. If the current
        session already had a prefetch (mid-conversation), we ALSO query
        for facts linked to entities from the conversation so far — this
        is what makes "Sher" answers grounded in Noyah context instead
        of generic.

        Filters out [GROUP RULE] entries when not in group/supergroup mode.
        """
        if not query or not query.strip():
            return ""

        cache_key = f"prefetch_{query.strip()[:200]}"
        cached = self._cache.get(cache_key) if self._cache else None
        if cached is not None:
            return cached

        is_group = self._chat_type in ("group", "supergroup")

        # Entity types that carry strategy context — NOT identity/dna noise.
        # project/general/user_pref/memory_entry/rule are the facts that
        # answer "who is Sher", "what is Noyah", "what did we decide".
        # identity/dna are already injected in the system prompt block.
        PREFERRED_TYPES = {
            "project", "general", "user_pref", "memory_entry",
            "rule", "directive", "goal",
        }

        # ── Phase 1: vector-primary hybrid search over knowledge ─────
        # Vector recall is the primary semantic path (nearest-neighbor to
        # the query). FTS is only a crutch inside hybrid_search_knowledge
        # when pgvector/Ollama is unavailable — never a gate that swallows
        # semantic results. Row shape is identical to _search_knowledge,
        # so _dedup_add and Phase 3 filtering work unchanged.
        ranked: list[dict] = []
        seen_ids: set[int] = set()

        def _dedup_add(row: dict) -> None:
            rid = row.get("id")
            if rid is not None:
                if rid in seen_ids:
                    return
                seen_ids.add(rid)
            ranked.append(row)

        try:
            results, _ = hybrid_search_knowledge(query, 8)
            for r in results:
                desc = (r.get("description") or "")
                if not is_group and desc.startswith("[GROUP RULE]"):
                    continue
                _dedup_add(r)
        except Exception:
            pass

        # ── Phase 2: entity probes for capitalized terms ─────────────
        # Filter out sentence starters and stopwords so "From" doesn't
        # beat "Noyah". Rank probes by how strongly the entity appears
        # in the query (longest match first = more specific).
        entities = _extract_entities(query)
        STOPWORDS = {
            "from", "when", "what", "which", "where", "how", "why",
            "the", "and", "for", "with", "are", "you", "your", "her",
            "his", "she", "he", "its", "this", "that", "these", "those",
            "there", "here", "then", "than", "also", "into", "onto",
            "about", "would", "could", "should", "will", "shall", "can",
            "not", "but", "or", "if", "so", "do", "does", "did", "is",
            "am", "are", "was", "were", "be", "been", "being", "have",
            "has", "had", "it", "i", "me", "my", "mine", "we", "us",
            "our", "they", "them", "their", "it's", "don't", "isn't",
            "aren't", "wasn't", "weren't", "can't", "won't", "wouldn't",
        }
        entities = [
            e for e in entities
            if e.lower() not in STOPWORDS
            and len(e) > 1
        ]
        # Sort by length desc so more specific names ("Sher Fenn")
        # probe before loose tokens ("Sher").
        entities.sort(key=len, reverse=True)

        for ent in entities[:4]:
            try:
                results = _probe_entity(ent, 5)
                for r in results:
                    desc = (r.get("description") or "")
                    if not is_group and desc.startswith("[GROUP RULE]"):
                        continue
                    _dedup_add(r)
            except Exception:
                pass

        # ── Phase 3: keep the strongest, render compactly ────────────
        # Prefer project/general/user_pref over noise; cap at 6 facts.
        kept: list[dict] = []
        for r in ranked:
            if r.get("entity_type") in PREFERRED_TYPES:
                kept.append(r)
            if len(kept) >= 6:
                break

        if not kept:
            return ""

        lines = ["[JPM Knowledge]"]
        for r in kept:
            etype = r.get("entity_type", "fact")
            name = r.get("name", "")
            desc = (r.get("description") or "").strip()
            if not desc:
                continue
            # Longer excerpts for project/general — these carry the
            # strategy that generic answers miss.
            excerpt_len = 160 if etype in ("project", "general") else 100
            excerpt = desc if len(desc) <= excerpt_len else desc[:excerpt_len] + "..."
            lines.append(f"  [{etype}] {name}: {excerpt}")

        result = "\n".join(lines)
        if self._cache:
            self._cache.set(cache_key, result)
        return result

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        pass

    def sync_turn(self, user_content: str, assistant_content: str, *,
                  session_id: str = "", messages: list | None = None) -> None:
        """Update state from tone detection on every turn (companion role only)."""
        if _detect_tone is None or _set_mia is None:
            return
        try:
            if not user_content:
                return
            tone = _detect_tone(user_content)
            _set_mia(tone["mood"], tone["energy"], tone["headspace"])
        except Exception:
            LOG.debug("jpm: sync_turn tone detect failed", exc_info=True)

    def get_tool_schemas(self) -> list[dict]:
        # The model-facing tool is registered ONCE, by the mea_vault plugin, under
        # the bare name ``vault``. Exposing JPM_SCHEMA here too would register a
        # SECOND name (``jpm``) for the same engine — the model then picks the
        # un-guided one and the routing table in the vault guidance is ignored.
        # Keep the provider tool-less; it still supplies prefetch + prompt block.
        return []

    def handle_tool_call(self, tool_name: str, args: dict, **kwargs) -> str:
        if tool_name == "jpm":
            return self._handle_jpm(args)
        return f"**jpm error:** unknown tool '{tool_name}'"

    def _handle_jpm(self, args: dict) -> str:
        """Unified dispatcher for the jpm tool — routes by action."""
        action = args.get("action", "")
        section = args.get("section", "")
        # Coerce fact_id (arrives as a JSON string from the tool schema) to an
        # int so downstream bigint binds / arithmetic never hit asyncpg's
        # "'str' object cannot be interpreted as an integer". Non-numeric or
        # missing stays None (each handler reports its own fact_id-required error).
        fact_id = args.get("fact_id")
        if fact_id is not None and fact_id != "":
            try:
                fact_id = int(fact_id)
            except (ValueError, TypeError):
                fact_id = None
            # Persist the coerced value back into args so the sub-handlers
            # (_handle_fact_store / _handle_fact_feedback) which re-read
            # args.get("fact_id") receive the int, not the raw string.
            args["fact_id"] = fact_id

        if action == "fetch":
            if not section:
                return "**jpm error:** section is required for fetch"
            return _handle_jpm_fetch(args)

        if action == "update" and not fact_id:
            if not section:
                return "**jpm error:** section is required for update (section write)"
            return _handle_jpm_update(args)

        if action in ("add", "get", "search", "probe", "related", "reason",
                      "contradict", "list", "update", "remove"):
            return self._handle_fact_store(args)

        if action in ("helpful", "unhelpful"):
            return self._handle_fact_feedback(args)

        if action in ("tables", "schema", "query", "row", "create_table", "rename_table", "index"):
            return self._handle_sql(args)

        return f"**jpm error:** unknown action '{action}'"

    def shutdown(self) -> None:
        if self._cache:
            self._cache.clear()
        _pg_shutdown()
        LOG.info("jpm: shutdown complete")

    def on_session_end(self, messages: list | None = None) -> None:
        pulse = _get_latest_pulse()
        if not pulse:
            _write_pulse("idle", "", self._session_id)
        LOG.info("jpm: memory extraction on session: %s", self._session_id)

    def on_memory_write(self, action: str, target: str, content: str,
                        metadata: dict | None = None) -> None:
        """Mirror built-in memory writes as knowledge entries."""
        if action == "add" and content:
            entity_type = "user_pref" if target == "user" else "general"
            _name = content.split(".")[0][:256] if "." in content else content[:256]
            _add_knowledge(entity_type, _name, content)
        elif action == "remove" and content:
            try:
                with sync_conn() as conn:
                    conn.execute("UPDATE knowledge SET archived = 1 WHERE description LIKE ? LIMIT 1",
                               (f'%{content[:100]}%',))
                _get_cache().invalidate("knowledge_")
            except Exception:
                pass

    def get_config_schema(self) -> list[dict]:
        return [
            {"key": "db_path", "description": "Database path or PG config", "default": "/root/.joshaico/memory/persistent_memory.db"},
            {"key": "default_trust", "description": "Default trust score for new facts", "default": "0.5"},
        ]

    def save_config(self, values: dict, joshaico_home: str) -> None:
        config_path = Path(joshaico_home) / "config.yaml"
        try:
            import yaml
            existing = {}
            if config_path.exists():
                with open(config_path, encoding="utf-8-sig") as f:
                    existing = yaml.safe_load(f) or {}
            existing.setdefault("plugins", {})
            existing["plugins"]["jpm"] = values
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(existing, f, default_flow_style=False)
        except Exception:
            pass

    def _handle_fact_store(self, args: dict) -> str:
        action = args.get("action", "")
        content = args.get("content", "")
        query = args.get("query", "")
        entity = args.get("entity", "")
        entities = args.get("entities", [])
        category = args.get("category", "general")
        tags = args.get("tags", "")
        fact_id = args.get("fact_id")
        limit = min(args.get("limit", 10), 50)
        min_weightage = args.get("min_weightage", 0.3)

        def _xe(s: str) -> str:
            # Markdown-safe: escape backticks and strip control chars.
            s = s.replace("`", "\\`")
            s = "".join(ch for ch in s if ch >= " " or ch in "\t\n\r")
            return s

        if action == "add":
            if not content:
                return "**jpm error:** content required for add"
            try:
                # Cap auto-add at 0.75. Only agent-created rules may reach
                # xhigh/high (> 0.75) hard injection via the memory tool;
                # programmatic adds must stay below that ceiling.
                _weightage = min(0.75, max(0.0, float(args.get("weightage", 0.5))))
            except (ValueError, TypeError):
                _weightage = 0.5
            _name = args.get("name", "")
            if not _name:
                _name = content.split(".")[0][:256] if "." in content else content[:256]
            _fingerprint = args.get("fingerprints", "")
            # fingerprint column is `text` — coerce dict/list/other non-strings to
            # a JSON string so the documented `fingerprints={"aliases": [...]}` shape
            # can never produce a DataError in _add_knowledge.
            if not isinstance(_fingerprint, str):
                try:
                    _fingerprint = json.dumps(_fingerprint, ensure_ascii=False)
                except (TypeError, ValueError):
                    _fingerprint = str(_fingerprint)
            if not _add_knowledge(category, _name, content, _weightage, _fingerprint):
                return "**jpm error:** failed to store knowledge entry (see logs)"
            return f"**jpm add ok** · category `{category}` · id stored"

        elif action == "get":
            if not fact_id:
                return "**jpm error:** fact_id required for get"
            _table = args.get("table", "knowledge")
            try:
                with sync_conn() as conn:
                    if _table == "knowledge":
                        row = conn.fetchone(
                            """SELECT id, entity_type, name, description, fingerprint, weightage,
                                      last_referenced, retrieval_count, helpful_count
                              FROM knowledge WHERE id = ? AND archived = 0""",
                            (fact_id,)
                        )
                        if not row:
                            return f"**jpm get** · table `{_table}` · count 0"
                        return (
                            f"**jpm get** · id `{row['id']}` · table `{_table}` · type `{row['entity_type']}` · trust {row['weightage']:.2f}\n"
                            f"- **name:** {row['name']}\n"
                            f"- **description:** {row['description']}\n"
                            f"- **fingerprint:** {row['fingerprint'] or ''}\n"
                            f"- **last_referenced:** {row['last_referenced']}"
                        )
                    else:
                        # Generic table: fetch all columns as key-value pairs.
                        # Resolve bare user-table names to their physical user_* name.
                        phys = _user_phys_name(conn, _table)
                        row = conn.fetchone(
                            f"""SELECT * FROM {_quote_ident(phys)} WHERE id = ?""",
                            (fact_id,)
                        )
                        if not row:
                            return f"**jpm get** · table `{_table}` · count 0"
                        parts = [f"**jpm get** · id `{row['id']}` · table `{_table}`"]
                        for k, v in row.items():
                            if v is not None:
                                parts.append(f"- **{k}:** {v}")
                        return "\n".join(parts)
            except Exception:
                return f"**jpm error:** failed to fetch entry from `{_table}`"

        elif action == "search":
            if not query:
                return "**jpm error:** query required for search"
            _table = args.get("table", "knowledge")
            # `search` is a full-text search over knowledge-style tables
            # (knowledge, sessions, messages, ...). User tables aren't indexed
            # for FTS — route them to `query` instead so bare names rewrite
            # correctly, rather than silently returning count 0.
            try:
                with sync_conn() as conn:
                    phys = _user_phys_name(conn, _table)
            except Exception:
                phys = _table
            if phys.startswith(_USER_PREFIX):
                return (f"**jpm search** · table `{_table}` is a user table "
                        f"(`{phys}`) — use `jpm query` (SQL) to query it; `search` "
                        f"only full-text-searches knowledge-style tables.")
            try:
                _offset = int(args.get("offset", 0))
            except (ValueError, TypeError):
                _offset = 0
            try:
                _min_trust = float(args.get("min_weightage", 0.3))
            except (ValueError, TypeError):
                _min_trust = 0.3
            if hybrid_enabled() and _table in ("knowledge", "sessions", "messages", "reflections", "patterns", "skills"):
                from ._hybrid_search import hybrid_search_knowledge
                results, has_more = hybrid_search_knowledge(query, limit, _offset, _table)
            else:
                results, has_more = _search_knowledge(query, limit, _offset, _table)
            if not results:
                return f"**jpm search** · table `{_table}` · count 0"

            if _table == "knowledge":
                # Knowledge results have weightage, entity_type, name, description
                filtered = [r for r in results if r.get("weightage", 0.5) >= _min_trust]
                if not filtered:
                    return f"**jpm search** · table `{_table}` · count 0 · _note: {len(results)} raw results below trust threshold {_min_trust}"
                _next_offset = _offset + limit if has_more else None
                parts = [f"## jpm search · table `{_table}` · count {len(filtered)} · offset {_offset}" + (f" · next_offset {_next_offset}" if _next_offset is not None else "")]
                for r in filtered:
                    trust = r.get("weightage", 0.5)
                    name = r.get("name", "")
                    desc = r.get("description", "")[:100]
                    body = name + (" — " + desc if desc else "")
                    parts.append(
                        f"- **id {r['id']}** · type `{r['entity_type']}` · trust {trust:.2f} — {body}"
                    )

                # Session breadcrumbs — recent sessions mentioning the query
                # AGENT MUST CHECK: these are sessions where this topic was discussed
                # NOTE: sessions has no search_vector column (verified in
                # _schema_pg.sql), so we match on title ILIKE instead of FTS.
                try:
                    with sync_conn() as conn:
                        srows = conn.fetchall(
                            """SELECT s.id, s.title, s.started_at, s.message_count
                              FROM sessions s
                              WHERE s.title ILIKE ?
                                AND s.archived = 0
                              ORDER BY s.started_at DESC
                              LIMIT 3""",
                            (f"%{query}%",)
                        )
                        if srows:
                            parts.append("  **Recent sessions mentioning this topic:**")
                            for s in srows:
                                title = s.get("title", "") or "untitled"
                                ts = s.get("started_at", 0)
                                from datetime import datetime
                                when = datetime.fromtimestamp(ts, tz=_LOCAL_TZ).strftime("%b %d, %Y") if ts else "?"
                                parts.append(
                                    f"  - `{s['id']}` · {title} · {when} · {s['message_count']} msgs"
                                )
                except Exception:
                    pass
            else:
                # Generic table results — just show id + title
                _next_offset = _offset + limit if has_more else None
                parts = [f"## jpm search · table `{_table}` · count {len(results)} · offset {_offset}" + (f" · next_offset {_next_offset}" if _next_offset is not None else "")]
                for r in results:
                    parts.append(
                        f"- **id {r.get('id', '')}** — {str(r.get('title', ''))[:200]}"
                    )

            return "\n".join(parts)

        elif action == "probe":
            if not entity:
                return "**jpm error:** entity required for probe"
            results = _probe_entity(entity, limit)
            if not results:
                return f"**jpm probe** · entity `{entity}` · count 0"
            parts = [f"## jpm probe · entity `{entity}` · count {len(results)}"]
            for r in results:
                trust = r.get("weightage", 0.5)
                name = r.get("name", "")
                desc = r.get("description", "")[:100]
                body = name + (" — " + desc if desc else "")
                parts.append(
                    f"- **id {r['id']}** · type `{r['entity_type']}` · trust {trust:.2f} — {body}"
                )
            return "\n".join(parts)

        elif action == "related":
            if not entity:
                return "**jpm error:** entity required for related"
            results = _related_entities(entity, limit)
            if not results:
                return f"**jpm related** · entity `{entity}` · count 0"
            parts = [f"## jpm related · entity `{entity}` · count {len(results)}"]
            for r in results:
                trust = r.get("weightage", 0.5)
                name = r.get("name", "")
                desc = r.get("description", "")[:100]
                body = name + (" — " + desc if desc else "")
                parts.append(
                    f"- **id {r['id']}** · type `{r['entity_type']}` · trust {trust:.2f} — {body}"
                )
            return "\n".join(parts)

        elif action == "reason":
            if not entities:
                return "**jpm error:** entities required for reason"
            results = _reason_entities(entities, limit)
            if not results:
                return "**jpm reason** · count 0"
            parts = [f"## jpm reason · count {len(results)}"]
            for r in results:
                trust = r.get("weightage", 0.5)
                name = r.get("name", "")
                desc = r.get("description", "")[:100]
                body = name + (" — " + desc if desc else "")
                parts.append(
                    f"- **id {r['id']}** · type `{r['entity_type']}` · trust {trust:.2f} — {body}"
                )
            return "\n".join(parts)

        elif action == "list":
            try:
                with sync_conn() as conn:
                    rows = conn.fetchall("SELECT id, entity_type, name, description, weightage FROM knowledge WHERE archived = 0 ORDER BY id DESC LIMIT ?", (limit,))
                    if not rows:
                        return "**jpm list** · count 0"
                    parts = [f"## jpm list · count {len(rows)}"]
                    for r in rows:
                        desc = r["description"][:100] if r["description"] else ""
                        body = r["name"] + (" — " + desc if desc else "")
                        parts.append(
                            f"- **id {r['id']}** · type `{r['entity_type']}` · trust {r['weightage']:.2f} — {body}"
                        )
                    return "\n".join(parts)
            except Exception as e:
                return f"**jpm error:** {e}"

        elif action == "update":
            if not fact_id:
                return "**jpm error:** fact_id required for update"
            weight_delta = args.get("weight_delta", 0)
            n = _update_trust(fact_id, weight_delta)
            if n < 0:
                return f"**jpm error:** failed to update weightage for id={fact_id} (see logs)"
            if n == 0:
                return f"**jpm error:** no fact found with id={fact_id}"
            return f"**jpm update ok** · id `{fact_id}`"

        elif action == "remove":
            if not fact_id:
                return "**jpm error:** fact_id required for remove"
            try:
                with sync_conn() as conn:
                    conn.execute("UPDATE knowledge SET archived = 1 WHERE id = ?", (fact_id,))
                _get_cache().invalidate("knowledge_")
                return f"**jpm remove ok** · id `{fact_id}`"
            except Exception as e:
                return f"**jpm error:** {e}"

        elif action == "contradict":
            if not query:
                return "**jpm error:** query required for contradict"
            results, _ = _search_knowledge(query, limit)
            if not results or len(results) < 2:
                return "**jpm contradict** · count 0"
            by_type: dict[str, list[dict]] = {}
            for r in results:
                by_type.setdefault(r['entity_type'], []).append(r)
            parts = [f"## jpm contradict · count {len(results)}"]
            for etype, entries in by_type.items():
                for r in entries:
                    trust = r.get("weightage", 0.5)
                    name = r.get("name", "")
                    desc = r.get("description", "")[:100]
                    body = name + (" — " + desc if desc else "")
                    parts.append(
                        f"- **id {r['id']}** · type `{etype}` · trust {trust:.2f} — {body}"
                    )
                names_seen: dict[str, list[str]] = {}
                for r in entries:
                    names_seen.setdefault(r['name'], []).append(r['description'][:80])
                for name, descs in names_seen.items():
                    if len(descs) >= 2 and len(set(descs)) > 1:
                        parts.append(
                            f"  ⚠️ **conflict:** `{name}` — {len(descs)} different descriptions"
                        )
            return "\n".join(parts)

        return f"**jpm error:** unknown action '{_xe(action)}'"

    def _handle_fact_feedback(self, args: dict) -> str:
        action = args.get("action", "")
        fact_id = args.get("fact_id")

        if not fact_id:
            return "**jpm error:** fact_id required"

        if action == "helpful":
            n = _update_trust(fact_id, 0.05)
            if n < 0:
                return f"**jpm error:** failed to mark helpful for id={fact_id} (see logs)"
            if n == 0:
                return f"**jpm error:** no fact found with id={fact_id}"
            return f"**jpm helpful ok** · id `{fact_id}`"
        elif action == "unhelpful":
            n = _update_trust(fact_id, -0.10)
            if n < 0:
                return f"**jpm error:** failed to mark unhelpful for id={fact_id} (see logs)"
            if n == 0:
                return f"**jpm error:** no fact found with id={fact_id}"
            return f"**jpm unhelpful ok** · id `{fact_id}`"

        return f"**jpm error:** unknown feedback action '{action}'"

    def _handle_sql(self, args: dict) -> str:
        """Handle schema browsing and arbitrary SQL (lite pgadmin).

        Actions:
          tables — list all tables in the schema
          schema — describe a table's columns/types/nullability (table=)
          query  — run arbitrary SQL (sql=, optional params= for $1/$2 placeholders)

        query runs read AND write SQL. SELECT/WITH return rows; other
        statements return an affected-row count. The PG connection is
        handled internally via sync_conn() — the agent never touches
        credentials.
        """
        action = args.get("action", "")

        def _xe(s: str) -> str:
            # Markdown-safe: escape backticks and strip control chars.
            s = s.replace("`", "\\`")
            s = "".join(ch for ch in s if ch >= " " or ch in "\t\n\r")
            return s

        def _ident(s: str) -> str:
            """Quote a PG identifier safely (double-quote, escape embedded quotes).

            Handles schema-qualified names (public.tab) by quoting each part
            separately so they don't collapse into one quoted literal.
            """
            return ".".join('"' + p.replace('"', '""') + '"' for p in str(s).split("."))

        def _is_simple_ident(s: str) -> bool:
            """True if s is a bare identifier (safe to _ident-quote)."""
            return bool(s) and all(c.isalnum() or c == "_" for c in s) and not s[0].isdigit()

        try:
            with sync_conn() as conn:
                if action == "tables":
                    # List tables across ALL non-system schemas (public + any
                    # user schemas like yachting.*), grouped by schema so jpm
                    # can introspect the whole DB, not just public.
                    rows = conn.fetchall(
                        "SELECT table_schema, table_name FROM information_schema.tables "
                        "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                        "  AND table_schema NOT LIKE 'pg\\_%' "
                        "ORDER BY table_schema, table_name"
                    )
                    if not rows:
                        return "**jpm tables** · count 0"
                    parts = [f"## jpm tables · count {len(rows)}"]
                    cur_schema = None
                    for r in rows:
                        sch = r["table_schema"]
                        if sch != cur_schema:
                            parts.append(f"\n### schema `{sch}`")
                            cur_schema = sch
                        parts.append(f"- `{r['table_name']}`")
                    return "\n".join(parts)

                if action == "schema":
                    table = args.get("table", "")
                    if not table:
                        return "**jpm error:** table required for schema"
                    # Support schema-qualified names (yachting.yachts_for_sale)
                    # as well as bare user tables. If a schema qualifier is
                    # present, resolve only the table part against the user
                    # prefix map, then introspect within that schema.
                    table = _user_phys_name(conn, table)
                    if "." in str(table):
                        schema_q, table_base = str(table).rsplit(".", 1)
                    else:
                        schema_q, table_base = "public", str(table)
                    rows = conn.fetchall(
                        "SELECT column_name, data_type, is_nullable, column_default "
                        "FROM information_schema.columns "
                        "WHERE table_schema = ? AND table_name = ? "
                        "ORDER BY ordinal_position",
                        (schema_q, table_base)
                    )
                    if not rows:
                        return f"**jpm schema** · table `{table}` · count 0"
                    parts = [f"## jpm schema · table `{table}` · count {len(rows)}"]
                    for r in rows:
                        parts.append(
                            f"- **{r['column_name']}** · `{r['data_type']}` · nullable={r['is_nullable']} · default={r['column_default'] or ''}"
                        )
                    return "\n".join(parts)

                if action == "create_table":
                    # create_table with name= + columns= (list of "name type [constraints]")
                    # or raw sql= for full CREATE TABLE control.
                    name = args.get("name", "")
                    columns = args.get("columns") or []
                    sql = args.get("sql", "")
                    if sql:
                        # Raw DDL path: rewrite bare user-table refs just in case
                        # the caller referenced an existing user table, and run.
                        user_map = _load_user_table_map(conn)
                        conn.execute(_rewrite_user_table_refs(sql, user_map))
                        return f"**jpm create_table ok** · rows_affected {conn.rowcount}"
                    if not name or not columns:
                        return "**jpm error:** create_table requires name= and columns= (or sql=)"
                    if not isinstance(columns, list):
                        return "**jpm error:** create_table columns= must be a list of name/type strings"
                    # Auto-add an `id` primary key column and a `timestamp` column if
                    # the caller didn't specify one of each. Every other table in the
                    # DB has an `id` PK and a `timestamp` (messages uses `timestamp`),
                    # so agents naturally assume they exist and query `WHERE id = ...`
                    # or filter/sort by time. Without these, a table created without
                    # them fails with `column "id"/"timestamp" does not exist`.
                    lower_cols = [str(c).strip().lower().split()[0] for c in columns]
                    if "id" not in lower_cols:
                        columns = ["id bigserial PRIMARY KEY"] + list(columns)
                    if "timestamp" not in lower_cols:
                        columns = columns + ["timestamp timestamp without time zone DEFAULT CURRENT_TIMESTAMP"]
                    col_sql = ", ".join(str(c) for c in columns)
                    # Auto-prefix user-created tables so they don't mix with core
                    # tables in the public schema. Agents keep referring to the bare
                    # name; _rewrite_user_table_refs() resolves it transparently.
                    phys_name = name
                    if not str(name).startswith(_USER_PREFIX):
                        phys_name = _USER_PREFIX + str(name)
                    ddl = f"CREATE TABLE IF NOT EXISTS {_ident(phys_name)} ({col_sql})"
                    conn.execute(ddl)
                    return f"**jpm create_table ok** · table `{phys_name}` · rows_affected {conn.rowcount}"

                if action == "rename_table":
                    name = args.get("name", "")
                    new_name = args.get("new_name", "")
                    if not name or not new_name:
                        return "**jpm error:** rename_table requires name= and new_name="
                    # Resolve bare user-table names to their physical user_* name.
                    phys = _user_phys_name(conn, name)
                    conn.execute(f"ALTER TABLE {_ident(phys)} RENAME TO {_ident(new_name)}")
                    return f"**jpm rename_table ok** · `{name}` → `{new_name}`"

                if action == "index":
                    # index with op= (create/drop/rebuild/list), name=, table=, columns=
                    op = args.get("op", "list")
                    name = args.get("name", "")
                    table = args.get("table", "")
                    columns = args.get("columns") or []
                    if op == "list":
                        if not table:
                            return "**jpm error:** index list requires table="
                        # Resolve bare user-table names to physical user_* name.
                        phys = _user_phys_name(conn, table)
                        rows = conn.fetchall(
                            "SELECT indexname, indexdef FROM pg_indexes "
                            "WHERE schemaname = 'public' AND tablename = ? ORDER BY indexname",
                            (phys,)
                        )
                        if not rows:
                            return f"**jpm index list** · table `{table}` · count 0"
                        parts = [f"## jpm index list · table `{table}` · count {len(rows)}"]
                        for r in rows:
                            parts.append(f"- **{r['indexname']}** — `{r['indexdef']}`")
                        return "\n".join(parts)
                    if op == "create":
                        if not name or not table or not columns:
                            return "**jpm error:** index create requires name=, table=, columns="
                        if not isinstance(columns, list):
                            return "**jpm error:** index create columns= must be a list of column names or expressions"
                        # Quote simple identifiers; pass functional expressions
                        # (e.g. lower(email)) through raw so they aren't quoted
                        # as a literal column name.
                        col_sql = ", ".join(
                            _ident(c) if _is_simple_ident(c) else str(c) for c in columns
                        )
                        # Resolve bare user-table names to physical user_* name.
                        phys = _user_phys_name(conn, table)
                        conn.execute(f"CREATE INDEX IF NOT EXISTS {_ident(name)} ON {_ident(phys)} ({col_sql})")
                        return f"**jpm index create ok** · name `{name}` · table `{table}`"
                    if op == "drop":
                        if not name:
                            return "**jpm error:** index drop requires name="
                        conn.execute(f"DROP INDEX IF EXISTS {_ident(name)}")
                        return f"**jpm index drop ok** · name `{name}`"
                    if op == "rebuild":
                        if not name:
                            return "**jpm error:** index rebuild requires name="
                        conn.execute(f"REINDEX INDEX {_ident(name)}")
                        return f"**jpm index rebuild ok** · name `{name}`"
                    return f"**jpm error:** unknown index op '{_xe(op)}'"

                if action == "query":
                    sql = args.get("sql", "")
                    if not sql:
                        return "**jpm error:** sql required for query"
                    params = args.get("params") or []
                    if not isinstance(params, list):
                        return "**jpm error:** query params= must be a list"
                    # Strip leading SQL comments so a commented SELECT still routes
                    # to fetchall (returns rows) instead of execute (rowcount 0).
                    stripped = sql.lstrip()
                    while stripped.startswith("/*"):
                        end = stripped.find("*/")
                        if end == -1:
                            break
                        stripped = stripped[end + 2 :].lstrip()
                    # Transparently resolve bare user-table refs (charter_fleet) to
                    # their physical user_<name> so agents keep using bare names
                    # regardless of the prefix. Only applies to tables that exist
                    # with the user_ prefix; core tables are untouched.
                    stripped = _rewrite_user_table_refs(stripped, _load_user_table_map(conn))
                    upper = stripped.upper()
                    is_select = (
                        upper.startswith("SELECT")
                        or upper.startswith("WITH")
                        or upper.startswith("EXPLAIN")
                        or upper.startswith("SHOW")
                        or upper.startswith("TABLE")
                        or upper.startswith("VALUES")
                    )
                    if is_select:
                        rows = conn.fetchall(stripped, params)
                        if not rows:
                            return "**jpm query** · count 0"
                        # Row cap: default 100 rows protects the agent's context
                        # window from a SELECT * on a huge table. Agents can pass
                        # limit= (1..MAX_QUERY_ROWS) to pull more rows when they know
                        # the result set is small. Paging beyond the cap is done with
                        # SQL OFFSET in the statement itself (e.g. LIMIT 1000 OFFSET 0).
                        MAX_QUERY_ROWS = 2000
                        raw_limit = args.get("limit")
                        try:
                            limit = int(raw_limit) if raw_limit is not None else 100
                        except (TypeError, ValueError):
                            limit = 100
                        limit = max(1, min(limit, MAX_QUERY_ROWS))
                        truncated = len(rows) > limit
                        rows = rows[:limit]
                        parts = [
                            f"## jpm query · count {len(rows)}"
                            + (" · truncated" if truncated else "")
                        ]
                        # Cell value truncation: default cuts each long value to
                        # _DEFAULT_VAL_LEN (100) chars so SELECT * over content
                        # columns can't flood the context. Pass truncate=0/off
                        # to return full cell values in one pass.
                        raw_val_len = args.get("truncate")
                        if raw_val_len is None:
                            val_len = _DEFAULT_VAL_LEN
                        else:
                            try:
                                val_len = int(raw_val_len)
                            except (TypeError, ValueError):
                                val_len = _DEFAULT_VAL_LEN
                        if val_len <= 0:
                            val_len = 0  # 0 / negative => full values
                        for r in rows:
                            cols = " · ".join(
                                # id/PK is always shown in full so the two-pass
                                # `row` action has a usable handle.
                                f"{k}={v}"
                                if k == "id"
                                else f"{k}={_truncate_cell(v, val_len)}"
                                for k, v in r.items()
                            )
                            parts.append(f"- {cols}")
                        return "\n".join(parts)
                    else:
                        # ── Destructive-statement guard ──────────────────────
                        # A single wrong jpm query must not be able to wipe the
                        # agent's own memory. DROP/TRUNCATE/DELETE/ALTER/REINDEX
                        # against a CORE table is hard-blocked. Against any
                        # other table it requires an explicit confirm=true.
                        first_kw = upper.split(None, 1)[0] if upper else ""
                        if first_kw in _DESTRUCTIVE_KEYWORDS:
                            # Pull the first table name referenced (the target
                            # of DROP/TRUNCATE/DELETE/ALTER). Best-effort: strip
                            # the keyword, skip any object-type keyword
                            # (TABLE/VIEW/INDEX/SEQUENCE/SCHEMA/COLUMN/...), then
                            # take the next identifier token as the target.
                            _OBJ_KW = {
                                "TABLE", "VIEW", "INDEX", "SEQUENCE", "SCHEMA",
                                "DATABASE", "COLUMN", "CONSTRAINT", "FUNCTION",
                                "TRIGGER", "MATERIALIZED", "TYPE", "ROLE", "USER",
                            }
                            target = ""
                            rest = stripped[len(first_kw):].lstrip()
                            # DELETE FROM <table> — the target follows FROM
                            if first_kw == "DELETE":
                                m = re.search(r"\bFROM\s+([`\"\w.]+)", rest, re.IGNORECASE)
                                target = (m.group(1) if m else "").strip('"').split(".")[-1].lower()
                            else:
                                # Skip IF EXISTS / IF NOT EXISTS (may appear
                                # before OR after the object keyword, e.g.
                                # "DROP IF EXISTS x" or "DROP TABLE IF EXISTS x")
                                def _skip_if(rest):
                                    while rest.upper().startswith("IF "):
                                        rest = rest.split(None, 2)[-1] if len(rest.split(None, 2)) > 2 else ""
                                    return rest
                                rest = _skip_if(rest)
                                # Skip object-type keywords (e.g. "TABLE" in
                                # "DROP TABLE knowledge", "MATERIALIZED VIEW" in
                                # "DROP MATERIALIZED VIEW x")
                                while True:
                                    tok = rest.split(None, 1)[0] if rest else ""
                                    if tok.upper() in _OBJ_KW:
                                        rest = rest.split(None, 1)[-1].lstrip() if len(rest.split(None, 1)) > 1 else ""
                                        rest = _skip_if(rest)
                                        continue
                                    break
                                # Take the first bare token (may be schema-qualified)
                                tok = rest.split(None, 1)[0] if rest else ""
                                target = tok.strip('"').split(".")[-1].lower()
                            if target in _CORE_TABLES:
                                return (
                                    f"**jpm error:** destructive statement on core table "
                                    f"`{_xe(target)}` is blocked — this table backs the "
                                    f"agent's own memory. Use the structured jpm actions "
                                    f"(add/update/remove) instead."
                                )
                            if not args.get("confirm"):
                                return (
                                    f"**jpm error:** destructive statement on table "
                                    f"`{_xe(target or '?')}` requires confirm=true to run. "
                                    f"Re-issue with confirm=true only if you are certain."
                                )
                        conn.execute(stripped, params)
                        return f"**jpm query ok** · rows_affected {conn.rowcount}"

                if action == "row":
                    # Pass-2 helper for query: fetch ONE full row by its primary
                    # key id (which query always shows in full) and return EVERY
                    # column with the FULL value — no cell truncation. This is
                    # the depth step of the two-pass pattern: query gives a fast
                    # triage list with values cut to _DEFAULT_VAL_LEN, then
                    # `row` table=<table> id=<pk> pulls the full row on demand.
                    _table = args.get("table", "")
                    _id = args.get("id")
                    if not _table:
                        return "**jpm error:** table required for row"
                    if _id is None:
                        return "**jpm error:** id (row primary key) required for row"
                    # Resolve bare user-table names (charter_fleet) to their
                    # physical user_* name, matching query/get behavior.
                    phys = _user_phys_name(conn, _table)
                    row = conn.fetchone(
                        f"SELECT * FROM {_ident(phys)} WHERE id = ?", (_id,)
                    )
                    if not row:
                        return f"**jpm row** · table `{_table}` · id `{_id}` · count 0"
                    parts = [f"## jpm row · id `{_id}` · table `{_table}`"]
                    for k, v in row.items():
                        if v is not None:
                            parts.append(f"- **{k}:** {v}")
                    return "\n".join(parts)

                return f"**jpm error:** unknown sql action '{_xe(action)}'"
        except Exception as e:
            msg = str(e)
            # Column-guessing guard: when a query references a column that
            # doesn't exist, tell the caller to inspect the real schema instead
            # of retrying with guessed names. Saves the burn of guess-and-retry.
            m = re.search(r'column "([^"]+)" does not exist', msg)
            if m:
                _bad = m.group(1)
                # best-effort: find the table in the statement
                tm = re.search(r"\b(?:FROM|UPDATE|INSERT INTO|INTO)\s+([`\"\w.]+)", msg, re.IGNORECASE)
                tbl = ""
                if tm:
                    tbl = " on `" + _xe(tm.group(1).strip('"').split(".")[-1]) + "`"
                return (
                    f"**jpm error:** column `{_xe(_bad)}` does not exist{tbl}. "
                    f"Run `jpm(action='schema', table='<table>')` (or `\\d <table>`) to "
                    f"see the actual columns before retrying."
                )
            return f"**jpm error:** {_xe(msg)}"