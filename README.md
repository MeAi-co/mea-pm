# mea_pm: your agent's memory, as a database

Most memory plugins hand your agent a bigger notebook. This one hands it a
database, a query language, and a reason to use both.

mea_pm is a PostgreSQL-backed memory provider for stock Hermes. Conversations,
facts, rules, entities, reflections and skills stop being a flat file that grows
until it crowds out the context window, and become rows in a store that survives
restarts, resets, reboots and compaction.

No core modifications. It plugs into the stock memory-provider seam and registers
ordinary tools on top of it.

---

## The short version

- **Memory is stored, not recited.** What gets injected each turn is a small
  curated slice. Everything else is retrieved on demand, by meaning, not by luck.
- **The store is central.** One Postgres instance serves the whole box: every
  profile, every chat, every topic, every cron job, all reading and writing the
  same rows, safely and at the same time.
- **`vault` is not a memory tool.** It is an interface to the store: recall,
  graph traversal, curation, schema inspection and arbitrary SQL. The agent can
  ask its memory questions instead of hoping the right paragraph was injected.

---

## Memory the agent actually uses

A memory system the agent does not actively use is a storage system with better
marketing. If facts go in and never come out unless a human asks, what you have is
a filing cabinet, not memory.

Memory has to be bi-directional and fluid. The agent writes because it decided
something was worth keeping, reads because it needs the answer, corrects what it
got wrong, and lets stale entries fade. That loop is the product. Storage is the
plumbing underneath it.

mea_pm is built around that loop, and then adds optional layers that improve the
experience of running it: tiered injection so the prompt stays small, warm start
so a new session is not a cold one, a stable and drift prompt split that keeps
prefix caching intact, skill nudges, recompaction, digest and toolflow loops. All
optional. None of them are the point, and each one can be switched off.

### The core difference from other memory plugins

| | Typical memory plugin | mea_pm |
|---|---|---|
| Does the agent store and retrieve on its own | Only when it is probed, or when the phrasing happens to trigger it. Otherwise nothing is written and nothing is read | The agent is expected to use the store: the guidance names it as the authority, the tool is cheap to call, and the write path is the same tool as the read path |
| Is tool use reliable | A coin toss. The same question twice can produce a retrieval one time and a confident guess the next | One tool name per capability, one owner per tool, and routing guidance in the prompt, so the model does not have two ways to do the same thing and pick neither |
| Where the answer comes from | Injected context. The agent repeats what was put in front of it and cannot tell you what it did not receive | A curated slice is injected and the rest is retrieved, so the agent can go past the injection and say where a fact came from |
| What happens after compaction | The injected block is the new memory. Anything dropped from it is gone | The rows are untouched and the agent re-queries them |

The third row is the one that changes behaviour. An agent that answers from
injection will answer confidently on the day its injection is wrong or stale, and
it has no way to find out. An agent that answers from retrieval can be asked
"where did that come from" and answer, because it has the row.

---

## Why flat memory stops working

Stock Hermes keeps memory in flat files under `$HERMES_HOME/memories/`. That
works until it doesn't. Three problems show up as soon as an agent gets real use.

**1. Memory competes with the conversation for context.** Every saved fact is
re-injected every turn. Past a few hundred entries the memory block crowds out
what you just said, and the agent starts answering from old notes.

**2. Nothing is searchable.** A flat file is a linear scan. "What did we decide
about the deploy pipeline three weeks ago" has no answer. The agent remembers it
by luck or not at all.

**3. It does not survive a reset.** `/new`, a session rollover or a gateway
restart starts the agent cold. Whatever it learned is gone unless it happened to
be written to a file, and a file that is re-read in full every turn is not a
memory, it is a liability.

mea_pm fixes all three by moving memory into Postgres with pgvector, and by
separating what gets injected from what gets retrieved.

---

## A central Postgres store beats a local memory plugin

This is the difference that matters most, and it is architectural rather than a
matter of tuning. A local memory plugin, the Mnemosyne pattern, keeps its state
in a file inside one agent's home directory and injects what it knows into the
prompt. That design is cheap to install and it hits a ceiling quickly.

| Dimension | Local memory plugin (file in one home) | mea_pm (central Postgres) |
|---|---|---|
| Where memory lives | A file inside one profile's directory | One Postgres database, shared by the box |
| Who can read it | That one agent, that one profile | Every profile, session, topic and cron job you point at it |
| Concurrent writers | One process, locks or corruption | Real transactions, real isolation, many writers |
| Recall | Whatever was injected, plus keyword hits | Vector search, entity probes and full text in one query |
| After compaction | The injected block is the memory | The rows are untouched, the agent re-queries them |
| Audit | Grep the file and hope | SQL. Every row, timestamp, weight and source |
| Growth | The file and the prompt grow together | The prompt stays fixed, the table grows |
| Backup | Copy a file mid-write | `pg_dump`, point in time, replicable |
| Beyond memory | Nothing, it is a memory file | Sessions, messages, skills, entities, reflections, pulses, arbitrary tables |

The practical consequences are not subtle.

**Compaction stops being amnesia.** When an agent's own context compression drops
the messages that held an answer, a file-backed plugin has already lost them into
the summary. A central store still has them, and the agent can go back and read
its own transcript instead of explaining why it cannot.

**Memory stops being per-agent.** A second profile, a background cron job, a
tooling session on another topic: they can all use the same store. A fact learned
in one session is available in the next without export, import or a sync script.
Identity lives in one place, and the entity graph is not fragmented into copies.

**The agent can be its own DBA.** Because the store is Postgres, the agent can
inspect it. It can list tables, describe a schema, run a query, and find out what
it actually knows instead of guessing from an injected sample. That is the
difference between an agent that recalls and an agent that investigates.

**Nothing is lost to a crash or a reboot.** The store is a server with a write
ahead log, not a file being rewritten in place while the gateway restarts.

---

## `vault` is more than a memory tool

`vault` exposes the engine's full dispatcher under one name, with twenty actions.
Grouped by what they are for:

**Recall and reading**

`fetch` (structured sections: pulse, active, loops, knowledge, reflections,
capabilities, task context), `search` (vector first, full text as a fallback),
`get` and `row` (one record, in full, by id), `list` (recent entries).

**The entity graph**

`probe` (everything linked to one entity), `related` (facts sharing entities),
`reason` (facts connected to several entities at once), `contradict` (entries that
disagree with each other). This is the part a flat file cannot do at all. It is
how an agent finds that two facts are about the same person, or that the store
holds two versions of the same decision.

**Curation**

`add`, `update`, `remove`, `helpful`, `unhelpful`. Each fact carries a weight, and
feedback moves it. An entry that repeatedly proves useful gets injected in full.
An entry that keeps proving stale drops to a breadcrumb and eventually out of the
prompt, while remaining searchable.

**The database itself**

`tables`, `schema`, `query`, `create_table`, `rename_table`, `index`. The agent can
run SQL against its own memory, create a table for a project it is tracking, and
inspect the schema when a query fails. Read and write, with the connection handled
inside the plugin, so no credentials ever enter the conversation.

That last group is what makes this something other than a memory plugin. A memory
plugin answers "what do you know about me". `vault` answers "what is in the store,
where did it come from, what contradicts it, and what happens if I aggregate it".
The same interface serves memory, history, skills and scratch tables.

---

## One box, many agents, many topics

A single store can serve several Hermes profiles at once, and the scoping is
deliberate rather than accidental:

- **Sessions** carry their profile, platform, chat and thread. Recall can cross
  any of those boundaries, which is what makes "we discussed this in another
  topic last week" answerable.
- **Knowledge** is scoped per profile by default, so one agent's private facts do
  not leak into another's prompt. Set `JPM_KNOWLEDGE_SCOPE=all` and the store
  becomes a shared brain instead.
- **Entities** stay shared. A person is the same person in every profile, and
  splitting the graph would fragment identity for no benefit. Facts pulled through
  the graph are still filtered by profile scope.
- **Skills** live in the same database, so a skill written in one session is
  visible to the next without copying files around.

Profile resolution uses core's own profile home lookup, not `os.environ`, because
one long-lived gateway process can serve turns for several profiles and the
environment describes the launch profile, not the current turn.

---

## What it does under the hood

### Tiered injection instead of a flat dump

Every knowledge entry carries a `weightage` between 0 and 1, and the provider uses
it to decide how much context the entry is worth:

| Weightage | What the agent sees |
|---|---|
| `>= 0.70` | Full text, injected every turn |
| `0.21 to 0.69` | A one line breadcrumb, enough to know it exists and can be fetched |
| `<= 0.20` | Nothing. Stored and searchable, never injected |

A hundred low value notes therefore cost a hundred breadcrumbs, not a hundred
paragraphs. The agent can still reach them. It is not forced to read them.

### Vector first recall

Before each turn the provider runs a hybrid search over the knowledge table:

```
pgvector nearest neighbour (embedding <=> query_vec)   primary path
        |
entity probes on capitalized names in the query        "who is X", "what is Y"
        |
full text search                                       graceful fallback only
```

The vector path is primary. Full text is reached when pgvector or the embedding
service is unavailable. It is a degradation net, never a gate that swallows
semantic results. If the embedding column is missing entirely, the provider logs
it once and falls back cleanly instead of failing the turn.

### A real schema, with a migration ledger

The engine ships a base schema plus numbered migrations, applied in order and
recorded in `_schema_migrations` so each runs exactly once. Upgrading is
`git pull` plus a restart. No manual SQL.

### Session continuity

Sessions, messages and their embeddings live in the same database as the facts.
That is what makes warm start, cross session recall and the `messages` and
`sessions` tools possible: the agent reads its own history instead of being told
about it.

---

## Architecture

```
mea_pm/
├── __init__.py          register(ctx) -> ctx.register_memory_provider(...)
├── plugin.yaml          manifest: deps, required env
├── install.sh           idempotent install (deps + import verify)
├── MIGRATION.md         stock Hermes to PG migration guide
├── jpm/                 vendored engine (do not edit; re-vendor)
│   ├── core/            provider, PG layer, search, schema, migrations
│   ├── ext/             state, tone, self improvement, side loop trace
│   └── scripts/         migrate_from_stock.py
├── side_loops/          optional companion plugins (see below)
└── bench/               evaluation reports + evidence
```

The provider itself is deliberately **tool-less**. It supplies the system prompt
sections and the per turn prefetch, and nothing else. The model facing tools
(`vault`, `messages`, `sessions`, `skills_*`) are registered by the side loop
plugins, so each tool has exactly one name and one owner. Registering a second
alias for the same engine causes the model to pick the unguided one and ignore the
routing guidance, so it is not done.

---

## Quickstart

### 1. Requirements

- PostgreSQL 14 or newer, with the **pgvector** extension available
- A stock Hermes install with an isolated runtime Python
- An embedding endpoint (Ollama with `nomic-embed-text` by default). Optional, but
  without it you get lexical search only

### 2. Install

```bash
cd <this dir>
./install.sh
```

Idempotent, prints each step, installs `ruamel.yaml`, `asyncpg`,
`psycopg2-binary` and `pyyaml` into the runtime interpreter, and verifies the
import. It never auto installs anything the manifest did not declare.

### 3. Configure

In the target profile's `.env`. Secrets go here, never in `config.yaml`:

```bash
JPM_PG_HOST=127.0.0.1
JPM_PG_PORT=5432
JPM_PG_DB=jpm
JPM_PG_USER=postgres
JPM_PG_PASSWORD=...
```

| Var | Required | Default |
|---|---|---|
| `JPM_PG_HOST` | **yes** | none |
| `JPM_PG_PORT` | no | `5432` |
| `JPM_PG_DB` | no | `jpm` |
| `JPM_PG_USER` | no | `postgres` |
| `JPM_PG_PASSWORD` | no | empty / `.pgpass` |
| `JPM_KNOWLEDGE_SCOPE` | no | `own` (`all` shares knowledge across profiles) |

> **`JPM_PG_HOST` is the one that bites.** If it is unset, the provider reports
> itself unavailable and the host silently falls back to its own memory backend.
> You get a working looking install that never touches Postgres. If it is set but
> unreachable, you get a hard error instead, which is the correct behaviour.

Embeddings (all optional):

| Var | Default |
|---|---|
| `EMBED_MODEL` | `nomic-embed-text` |
| `EMBED_DIM` | `768` |
| `EMBED_NUM_GPU` | `-1` (all) |
| `EMBED_BATCH` | `32` |
| `EMBED_WORKERS` | `2` |
| `OLLAMA_URL` | none |

### 4. Activate

```yaml
# config.yaml
memory:
  provider: mea_pm
```

Restart the gateway, or start a new session.

### 5. Verify

```bash
# did the schema apply? expect one row per file in jpm/core/_migrations
psql "$JPM_PG_HOST" -c "SELECT count(*) FROM _schema_migrations;"
```

Then ask the agent to run `vault(action='fetch', section='pulse')`. If the provider
is live it returns structured sections. If it silently returns nothing, check
`JPM_PG_HOST` first.

---

## Coming from stock Hermes

If you already have history in `$HERMES_HOME/state.db`, it does **not** move
automatically. The schema is created empty on first run.

See **[MIGRATION.md](MIGRATION.md)** for the full procedure, and:

```bash
python jpm/scripts/migrate_from_stock.py --help
```

The importer is dry run by default, idempotent, resumable, and opens the source
SQLite read only. It resolves paths from `HERMES_HOME`, with no hardcoded
locations.

---

## Side loops

`side_loops/` holds optional companion plugins that build on the same engine. Each
is independently installable, and none are required for the provider to work.

| Plugin | What it adds |
|---|---|
| `mea_vault` | the `vault` tool: memory CRUD, graph traversal, schema and SQL access |
| `mea_messages` | the `messages` tool: message level recall across sessions |
| `mea_sessions` | the `sessions` tool: session recall with vector search; **disables stock `session_search`** |
| `mea_skills` | `skills_list`, `skill_view`, `skill_manage` (PG backed overrides) plus `skill_choose` |
| `mea_warmstart` | replays the prior session's tail on a cold start |
| `mea_prompt` | stable and drift system prompt split (prefix cache safe) |
| `mea_loop_anchor` | volatile session anchor, generated out of process |
| `mea_loop_statesync` | turn end pulse, focus and loop sync |
| `mea_loop_selfimpr` | self improvement pass over recent turns |
| `mea_loop_skillmgr` | out of band skill manager turn classifier |
| `mea_loop_skillnudge` | skill load and maintenance nudges (capped per turn) |
| `mea_loop_recompact` | tier 2 session summary recompaction |
| `mea_loop_digest` | LLM row compressor, **cron driven**, no per turn hook |
| `mea_loop_toolflow` | non LLM tool flow summarizer, **cron driven** |
| `_mea_loops_core` | shared runtime for the loop plugins |

The two cron driven loops are marked because they are the ones people
misconfigure: they have no `post_llm_call` hook and will appear inert until you
schedule them.

---

## Evaluation

`bench/` holds the reports and the evidence behind them. These were **live tests
with a user and an assistant**, not a headless benchmark. Both arms ran as real
agents in Telegram conversations, with compression firing under load and tools
called for real.

The memory itself was seeded. Both arms ingested the same LongMemEval sessions
before the run, so the only variable is how that memory is stored and retrieved,
not what is known. Everything after the seed is live: a real user drives both
conversations in real time.

The questions were rewritten, not stock. Shipped LongMemEval items are simple XY
lookups, one field per question, which a single keyword hit can answer. The items
used here are vaguer and multi hop, so no single retrieval returns the answer and
the arm has to decide what to fetch next and reconcile what it finds. The
measurement is therefore tool use: which arm reconstructs the answer from the
memory it holds, and how many steps that takes.

That combination is what the synthetic benches miss. A fixed haystack queried in
one shot has no human, no turn to turn drift and no compaction step, so it cannot
show what happens when an agent's own compression quietly removes the messages
that held the answer.

Results were conclusive by the fourth scored run and stayed that way. See
`bench/README.md` for the method, the arm definitions, and the transcripts behind
each result.

---

## What this is not

- **Not a hosted service.** You run Postgres. That is the point, and it is also
  the operational cost.
- **Not conflict free across agents.** Two profiles can write contradictory facts
  about the same entity. `vault(action='contradict')` surfaces that instead of
  hiding it, but nothing resolves it for you.
- **Not useful without embeddings.** It runs without them, and recall degrades to
  keyword matching, which is the failure mode this project exists to replace.
- **Not a replacement for the model's context window.** It reduces what has to be
  carried, and it cannot make a small model reason better.

---

## Re-vendoring the engine

The `jpm/` tree is vendored, not developed here. To update it:

```bash
rsync -a --delete \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='_OLD' \
  /path/to/upstream/core/jpm/ ./jpm/
```

Then re-run `./install.sh` and restart. Migrations apply on the next provider init.

---

## License

MIT. See [LICENSE](LICENSE).
