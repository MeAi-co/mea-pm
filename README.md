# mea_pm — MEAI Persistent Memory

A PostgreSQL-backed memory provider for stock Hermes. Your agent's memory stops
being a flat file that grows until it overflows the context window, and becomes a
queryable database that survives restarts, session resets, and gateway reboots.

No core modifications. It plugs into the stock memory-provider seam.

---

## Why this exists

Stock Hermes keeps memory in flat files under `$HERMES_HOME/memories/`. That works
until it doesn't. Three problems show up as an agent gets real use:

**1. Memory competes with conversation for context.** Every fact you save is
re-injected every turn. Past a few hundred entries the memory block crowds out the
actual conversation, and the agent starts answering from stale notes instead of
what you just said.

**2. Nothing is searchable.** A flat file is a linear scan. "What did we decide
about the deploy pipeline three weeks ago" has no answer — the agent either
remembers it by luck or doesn't.

**3. It doesn't survive a reset.** `/new`, a session rollover, or a gateway restart
starts the agent cold. Whatever it learned in the previous session is gone unless
it happened to be written to a file.

mea_pm fixes all three by moving memory into PostgreSQL with pgvector, and by
splitting what gets injected from what gets *retrieved*.

---

## What it actually does

### Tiered injection instead of a flat dump

Every knowledge entry carries a `weightage` between 0 and 1. The provider uses it
to decide how much context each entry is worth:

| Weightage | What the agent sees |
|---|---|
| `>= 0.70` | Full text, injected every turn |
| `0.21 – 0.69` | A one-line breadcrumb pointer — enough to know it exists and can be fetched |
| `<= 0.20` | Nothing. Stored, searchable, not injected |

So a hundred low-value notes cost you a hundred breadcrumbs, not a hundred
paragraphs. The agent can still reach them — it just isn't forced to read them.

### Vector-first recall

Before each turn the provider runs a hybrid search over the knowledge table:

```
pgvector nearest-neighbour (embedding <=> query_vec)   ← primary path
        ↓
entity probes on capitalized names in the query       ← "who is X", "what is Y"
        ↓
FTS full-text                                          ← crutch only
```

The vector path is primary. Full-text search is reached **only** when pgvector or
the embedding service is unavailable — it is a graceful-degradation net, never a
gate that swallows semantic results. If the embedding column is missing entirely,
the provider logs it once and falls back cleanly rather than failing the turn.

### A real schema, with a migration ledger

The engine ships a base schema plus 63 numbered migrations, applied in order and
recorded in `_schema_migrations` so each runs exactly once. Upgrading is
`git pull` + restart — no manual SQL.

### Session continuity

Sessions, messages, and their embeddings live in the same database. That is what
makes warm start, cross-session recall, and the `sessions` / `messages` tools
possible: the agent can read its own history instead of being told about it.

---

## Architecture

```
mea_pm/
├── __init__.py          register(ctx) → ctx.register_memory_provider(...)
├── plugin.yaml          manifest: deps, required env
├── install.sh           idempotent install (deps + import verify)
├── MIGRATION.md         stock-Hermes → PG migration guide
├── jpm/                 vendored engine (do not edit; re-vendor)
│   ├── core/            provider, PG layer, search, schema, 63 migrations
│   ├── ext/             state, tone, self-improvement, side-loop trace
│   └── scripts/         migrate_from_stock.py
├── side_loops/          optional companion plugins (see below)
└── bench/               evaluation harness + reports
```

The provider itself is deliberately **tool-less**. It supplies the system-prompt
sections and the per-turn prefetch, and nothing else. The model-facing tools
(`vault`, `messages`, `sessions`, `skills_*`) are registered by the side-loop
plugins, so each tool has exactly one name and one owner. Registering a second
alias for the same engine causes the model to pick the un-guided one and ignore
the routing guidance — so it isn't done.

---

## Quickstart

### 1. Requirements

- PostgreSQL 14+ with the **pgvector** extension available
- A stock Hermes install with an isolated runtime Python
- An embedding endpoint (Ollama with `nomic-embed-text` by default) — optional,
  but without it you get lexical search only

### 2. Install

```bash
cd <this dir>
./install.sh
```

Idempotent, prints each step, installs `ruamel.yaml` / `asyncpg` /
`psycopg2-binary` / `pyyaml` into the runtime interpreter and verifies the import.
It never auto-installs anything the manifest didn't declare.

### 3. Configure

In the target profile's `.env` — secrets go here, never in `config.yaml`:

```bash
JPM_PG_HOST=127.0.0.1
JPM_PG_PORT=5432
JPM_PG_DB=jpm
JPM_PG_USER=postgres
JPM_PG_PASSWORD=...
```

| Var | Required | Default |
|---|---|---|
| `JPM_PG_HOST` | **yes** | — |
| `JPM_PG_PORT` | no | `5432` |
| `JPM_PG_DB` | no | `jpm` |
| `JPM_PG_USER` | no | `postgres` |
| `JPM_PG_PASSWORD` | no | empty / `.pgpass` |

> **`JPM_PG_HOST` is the one that bites.** If it is unset, the provider reports
> itself unavailable and the host silently falls back to its own memory backend.
> You get a working-looking install that never touches PostgreSQL. If it is set
> but unreachable, you get a hard error instead — which is the correct behaviour.

Embeddings (all optional):

| Var | Default |
|---|---|
| `EMBED_MODEL` | `nomic-embed-text` |
| `EMBED_DIM` | `768` |
| `EMBED_NUM_GPU` | `-1` (all) |
| `EMBED_BATCH` | `32` |
| `EMBED_WORKERS` | `2` |
| `OLLAMA_URL` | — |

### 4. Activate

```yaml
# config.yaml
memory:
  provider: mea_pm
```

Restart the gateway, or start a new session.

### 5. Verify

```bash
# schema applied?
psql "$JPM_PG_HOST" -c "SELECT count(*) FROM _schema_migrations;"   # expect 63

# provider live?
# ask the agent to run: vault(action='fetch', section='pulse')
```

---

## Coming from stock Hermes

If you already have history in `$HERMES_HOME/state.db`, it does **not** move
automatically. The schema is created empty on first run.

See **[MIGRATION.md](MIGRATION.md)** for the full procedure, and:

```bash
python jpm/scripts/migrate_from_stock.py --help
```

The importer is dry-run by default, idempotent, resumable, and opens the source
SQLite read-only. It resolves paths from `HERMES_HOME` — no hardcoded locations.

---

## Side loops

`side_loops/` holds optional companion plugins that build on the same engine.
Each is independently installable; none are required for the provider to work.

| Plugin | What it adds |
|---|---|
| `mea_vault` | the `vault` tool — memory CRUD + schema/SQL access |
| `mea_messages` | the `messages` tool — message-level recall across sessions |
| `mea_sessions` | the `sessions` tool — session recall with vector search; **disables stock `session_search`** |
| `mea_skills` | `skills_list` / `skill_view` / `skill_manage` (PG-backed overrides) + `skill_choose` |
| `mea_warmstart` | replays the prior session's tail on a cold start |
| `mea_prompt` | stable/drift system-prompt split (prefix-cache safe) |
| `mea_loop_anchor` | volatile session anchor, generated out-of-process |
| `mea_loop_statesync` | turn-end pulse / focus / loops sync |
| `mea_loop_selfimpr` | self-improvement pass over recent turns |
| `mea_loop_skillmgr` | out-of-band skill-manager turn classifier |
| `mea_loop_skillnudge` | skill load + maintenance nudges (capped per turn) |
| `mea_loop_recompact` | tier-2 session-summary recompaction |
| `mea_loop_digest` | LLM row compressor — **cron-driven**, no per-turn hook |
| `mea_loop_toolflow` | non-LLM tool-flow summarizer — **cron-driven** |
| `_mea_loops_core` | shared runtime for the loop plugins |

The two cron-driven loops are marked because they are the ones people misconfigure:
they have no `post_llm_call` hook and will appear inert until you schedule them.

---

## Evaluation

`bench/` contains the harness and the reports. See `bench/README.md` for the
methodology, the arm definitions, and the raw chat/gateway logs behind each result.

---

## Re-vendoring the engine

The `jpm/` tree is vendored, not developed here. To update it:

```bash
rsync -a --delete \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='_OLD' \
  /path/to/upstream/core/jpm/ ./jpm/
```

Then re-run `./install.sh` and restart. Migrations apply on next provider init.

---

## License

MIT — see [LICENSE](LICENSE).
