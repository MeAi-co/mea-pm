# JPM Memory — Source of Truth

All structured knowledge lives in `persistent_memory.db` (SQLite FTS5) at `$HERMES_HOME/memory/persistent_memory.db`.

## Architecture

### Two Injection Paths

**Path A — System prompt (primary):**
`patches/system_prompt.py` → `jpm/core/_provider.py` → `system_prompt_sections()` → queries knowledge DB by entity_type with weightage tiers → builds the JPM context block injected at session start.

**Path B — Hook callback (legacy, used by some nodes):**
`_hooks.py` → `pre_llm_call_callback()` → `_build_yaml()` → writes YAML to disk on first turn. Contains stale identity hardcode — being phased out in favor of Path A.

### Weightage Tiering

| Range | Behavior |
|---|---|
| `>= 0.70` | Full XML injection into system prompt |
| `0.40 - 0.69` | Breadcrumb only — "available via jpm()" |
| `< 0.40` | Skipped entirely |

### DB Schema

`knowledge` table has both `trust_score` (user feedback) and `weightage` (injection tiering). `weightage` is backfilled from `trust_score` on migration. Both columns coexist — `weightage` drives injection, `trust_score` drives search ranking.

## Tools

| Tool | Purpose |
|---|---|
| `jpm(action="fetch", section="...")` | Read pulse, active, loops, knowledge, reflections, capabilities, task_context |
| `jpm(action="update", section="...")` | Write pulse, active, loops, resolve_loop, knowledge, reflection, capability, task_context |
| `jpm(action="add", ...)` | Store new facts in knowledge (category, content, tags) |
| `jpm(action="search", query="...")` | FTS5 full-text search across all knowledge |
| `jpm(action="probe", entity="...")` | All facts linked to an entity |
| `jpm(action="related", entity="...")` | Facts sharing entities with a given entity |
| `jpm(action="reason", entities=[...])` | Facts connected to MULTIPLE entities simultaneously |
| `jpm(action="contradict", query="...")` | Find potentially conflicting facts |
| `jpm(action="list", ...)` | List recent facts |
| `jpm(action="helpful"/"unhelpful", fact_id=...)` | Rate fact — adjusts trust_score |
| `session_search(query="...")` | Search past session transcripts via FTS5 |
| `session_search(session_id="...")` | Read a specific session transcript |

## JPM Sections

| Section | Content |
|---|---|
| `pulse` | Session health — `status:nominal\|blocked\|degraded\|idle` |
| `active` | Current focus — `focus:<what> project:<proj> status:<ready\|blocked\|done>` |
| `loops` | Open/resolved issues — `content:<issue> project:<proj> priority:<high\|medium\|low>` |
| `knowledge` | FTS5-indexed entries — `entity_type:<type> name:<name> description:<text>` |
| `reflections` | Past insights — `insight:<lesson> trigger:<why> impact:<1-10>` |
| `capabilities` | Tool proficiency — auto-tracked |
| `task_context` | Project milestones — `project_name:<proj> milestone:<step> status:<pending\|done>` |

## Knowledge Entity Types

- `identity` — Agent identity/soul. Weightage >= 0.70 for full injection.
- `user_pref` — User preferences, workflow style, corrections. High weightage = always injected.
- `rule` — Hard rules (never delete, no silent failures, session-first, etc.). 0.90 weightage.
- `memory_entry` — Personal agent notes, shoebox entries. Tiered by importance.
- `project` — Architecture decisions and system design
- `tool` — Tool usage patterns
- `skill` — Registered skill metadata (backfilled from `$HERMES_HOME/skills/`)
- `skill_part` — Skill sub-parts (references, templates, scripts)
- `general` — General knowledge, session sweeps, legacy data
- `session_sweep` — Auto-mined session insights

## Context Injection Order

The `<jpm_context>` block is built in this order:

1. **Identity** — Full injection (xhigh by definition)
2. **User preferences** — Full for high weightage, breadcrumb for medium
3. **Memory entries** — Full for high weightage, breadcrumb for medium
4. **Rules** — Full for high weightage, wrapped in `<lookup>` tags
5. **N-1 session summary** — Previous session title + last exchange
6. **Agent state** — Current mood, energy, headspace, pulse, active focus, open loops

## Session Continuity

- Gateway restart preserves sessions via `resume_pending` flag — next message reloads transcript from SQLite
- `/new` should preserve session_id (being implemented)
- `/reset` creates fresh session_id with empty history

## Memory Pipeline

Scripts in `jpm/scripts/`:

- `migrate_from_stock.py` — Import an existing stock Hermes SQLite `state.db`
  (sessions + messages) into the PG tables. Dry-run by default; idempotent and
  resumable. See `MIGRATION.md` at the repo root.

Memory is **semi-automatic** — facts are stored explicitly during sessions.
There is no automatic skill backfill or dedup pipeline in this release.

## Trust Scoring

`jpm(action="helpful"/"unhelpful", fact_id=...)` adjusts trust (`+0.05` / `-0.10` per rating). Facts below `min_trust` (default 0.3) are hidden. This keeps good facts rising, stale facts sinking.

