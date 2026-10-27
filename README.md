# MeAI Vault™

**Permanent memory for stock Hermes agents.** MeAI Vault is the product. `mea_pm`
is the package it ships as, short for MEAI permanent memory.

Most AI tools suffer from short term memory loss. The second you close a chat
window or start a new task, they forget your rules, your history and your
preferences.

MeAI Vault exists to solve that exact problem. It is the backend engine that gives
an agent true persistent memory. Instead of resetting, the agent cross-references
your past notes, remembers key facts on demand, and keeps your full operational
context from the first turn to the last.

It is the assistant memory we wanted for our own daily work. That is why we built
it, and why we are giving it away.

Under the hood it is a PostgreSQL-backed memory provider: conversations, facts,
rules, entities, reflections and skills live as rows in a store that survives
restarts, resets, reboots and compaction. No core modifications, it plugs into the
stock memory-provider seam.

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

## Who it is for

MeAI Vault is aimed at **intermediate to advanced users**, and it assumes you are
comfortable with Postgres, environment files and reading a log when something
fails. It is not a one click install for a laptop toy.

It fits best when:

- **Your agents run on a VPS or a server.** A long lived gateway plus a database is
  the natural shape. Laptops sleep, and a store that is asleep is not memory.
- **You run more than one agent.** Several profiles, several topics, a cron job and
  a chat session, all needing the same memory without an export or a sync script.
- **Memory has to move fast between them.** One query path for everyone, no queue,
  no replication lag, no "which copy is current".
- **The assistant is long lived.** Its value is the accumulated rules, preferences
  and history, and you want that to survive resets and compaction.
- **You want to inspect what it knows.** SQL access to your own memory, with the
  schema and the rows visible instead of summarised into a prompt.

If you are after permanent memory for a Hermes agent that runs for months across
profiles, topics and cron jobs, this is the shape you want. If you want zero
dependencies and a single file, stock file memory is still the simpler choice, and
nothing here pretends otherwise.

---

## Requirements

| Requirement | Detail |
|---|---|
| Host | A VPS or server running the gateway continuously. Any Linux that runs Hermes and Postgres |
| PostgreSQL | 14 or newer, with the **pgvector** extension available |
| Embedding path | Local (Ollama with `nomic-embed-text` by default) or an external OpenAI compatible endpoint. `EMBED_DIM` must match the model |
| Runtime | The agent's own Python, which `install.sh` targets. No global install needed |
| Access | Shell on the host to run `install.sh` and the importer, and network from the gateway to the Postgres port |
| Storage | A disk with room for rows and embeddings, plus a backup target for `pg_dump` |
| Network | If Postgres is remote, a private network or TLS. Memory over the open internet is a bad trade |

Nothing else is required. The embedding service can be on the same box or a
separate one, and the provider degrades to keyword search if it disappears.

### Documentation your agent can follow

The repo ships the instructions, not just a paragraph of prose, so you can point
your own agent at them:

- **[MIGRATION.md](MIGRATION.md)** walks the stock to Postgres move, including what
  to check before and after.
- **`jpm/scripts/migrate_from_stock.py`** is dry run by default, idempotent,
  resumable, and opens the source SQLite read only. Nothing is destroyed on a first
  pass.
- **`install.sh`** is idempotent and verifies its own imports.

A capable agent can read those files itself and carry out the migration, which is
how this was deployed in the first place.

---

## Memory the agent actually uses

A memory system the agent does not actively use is a storage system with better
marketing. If facts go in and never come out unless a human asks, what you have is
a filing cabinet, not memory.

Memory has to be bi-directional and fluid. The agent writes because it decided
something was worth keeping, reads because it needs the answer, corrects what it
got wrong, and lets stale entries fade. That loop is the product. Storage is the
plumbing underneath it.

MeAI Vault is built around that loop, and then adds optional layers that improve
the experience of running it: tiered injection so the prompt stays small, warm start
so a new session is not a cold one, a stable and drift prompt split that keeps
prefix caching intact, skill nudges, recompaction, digest and toolflow loops. All
optional. None of them are the point, and each one can be switched off.

### The core difference from other memory plugins

| | Typical memory plugin | MeAI Vault |
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

MeAI Vault fixes all three by moving memory into Postgres with pgvector, and by
separating what gets injected from what gets retrieved. The result is permanent
agent memory rather than a session scratchpad: the store holds the facts, not the
prompt.

---

## A central Postgres store beats a local memory plugin

This is the difference that matters most, and it is architectural rather than a
matter of tuning. A local memory plugin, the Mnemosyne pattern, keeps its state
in a file inside one agent's home directory and injects what it knows into the
prompt. That design is cheap to install and it hits a ceiling quickly.

| Dimension | Local memory plugin (file in one home) | MeAI Vault (central Postgres) |
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
That is what makes permanent memory for a Hermes agent possible at all: warm start,
cross session recall, and the `messages` and `sessions` tools all read the same
rows, so the agent reads its own history instead of being told about it.

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

Repo: **https://github.com/MeAi-co/mea-pm.git**

Four steps. Clone it into the profile whose gateway runs your agent, install, point
it at Postgres, switch the provider on.

```bash
# 1. into the profile, as a plugin
git clone https://github.com/MeAi-co/mea-pm.git ~/.hermes/plugins/mea_pm
cd ~/.hermes/plugins/mea_pm && ./install.sh

# 2. credentials go in the profile .env, never in config.yaml
cat >> ~/.hermes/.env <<'EOF'
JPM_PG_HOST=127.0.0.1
JPM_PG_PORT=5432
JPM_PG_DB=jpm
JPM_PG_USER=postgres
JPM_PG_PASSWORD=change_me
EOF

# 3. switch the provider on
#    edit config.yaml and add:
#      memory:
#        provider: mea_pm
```

```bash
# 4. restart the gateway, then check the schema landed
psql "$JPM_PG_HOST" -c "SELECT count(*) FROM _schema_migrations;"
```

If that returns a row count, the store is live. Ask the agent for
`vault(action='fetch', section='pulse')` and it should come back structured.

**Prerequisites for those four steps:** Postgres 14 or newer with pgvector, and a
database the gateway user can reach. Embeddings are optional and only change
whether recall is semantic or lexical.

That is the whole install. Everything past this point is detail you can hand to
your agent: the variable table, the two failure modes, the embedding options and
the migration path are all written to be read by it.

### Every variable, and the two that bite

In the target profile's `.env`:

| Var | Required | Default |
|---|---|---|
| `JPM_PG_HOST` | **yes** | none |
| `JPM_PG_PORT` | no | `5432` |
| `JPM_PG_DB` | no | `jpm` |
| `JPM_PG_USER` | no | `postgres` |
| `JPM_PG_PASSWORD` | no | empty / `.pgpass` |
| `JPM_KNOWLEDGE_SCOPE` | no | `own` (`all` shares knowledge across profiles) |

> **`JPM_PG_HOST` is the one that bites.** Unset, the provider reports itself
> unavailable and the host falls back to its own memory backend. You get a working
> looking install that never touches Postgres. Set but unreachable, you get a hard
> error instead, which is the correct behaviour.

Embeddings, all optional. Without them recall is keyword only:

| Var | Default |
|---|---|
| `EMBED_MODEL` | `nomic-embed-text` |
| `EMBED_DIM` | `768` |
| `EMBED_NUM_GPU` | `-1` (all) |
| `EMBED_BATCH` | `32` |
| `EMBED_WORKERS` | `2` |
| `OLLAMA_URL` | none |

`install.sh` is idempotent, prints each step, installs `ruamel.yaml`, `asyncpg`,
`psycopg2-binary` and `pyyaml` into the runtime interpreter, and verifies the
import. It never installs anything the manifest did not declare.

---

## Reference configuration

These are the settings this stack actually ran with, not a guess. The two that
matter most are the plugin entries and the compression block.

```yaml
memory:
  provider: mea_pm

plugins:
  enabled:
    - mea-vault
    - mea-sessions
    - mea-messages
    - mea-skills
    - mea-prompt
    - mea-warmstart
  entries:
    mea-sessions:
      allow_tool_override: true    # let `sessions` replace stock session_search
    mea-skills:
      allow_tool_override: true    # let skills_* override the core tools
    mea-warmstart:
      settings:
        enabled: true
        on_cold_start: true
        on_boot: true
        last_n: 16
        max_chars: 7000
        min_messages: 4
        source: pg                 # replay from Postgres, not a flat file
        per_message_chars: 700

tools:
  tool_search:
    enabled: "off"                 # keep vault/sessions/messages directly visible

auxiliary:
  compression:
    model: <cheap fast model>      # summaries do not need the main model
    timeout: 120

compression:
  enabled: true
  threshold: 0.95                  # ratio trigger
  threshold_tokens: 100000         # absolute trigger, see note below
  proactive_prune_tokens: 60000    # deterministic tool result prune, no LLM
  micro_compact: true              # second deterministic pass, post turn
  micro_compact_every_n_turns: 3   # amortise the aux call, do not pay it every turn
  micro_compact_defrag_threshold_tokens: 12000
  micro_compact_timeout_seconds: 45
  protect_last_n: 20
  protect_first_n: 10
  in_place: true
```

Why these keys, briefly:

- **`tool_search.enabled: "off"`** keeps plugin tools on the advertised surface. The
  stock bridge defers every non core tool behind `tool_search`, which hides `vault`,
  `sessions` and `messages` while the prompt still names them. The agent then has
  guidance for tools it cannot see.
- **`allow_tool_override: true`** on sessions and skills is what makes the plugin
  version the one that answers. Without it the core tool wins and the store is not
  consulted.
- **`threshold_tokens`** gives an absolute trigger alongside the ratio. Set it near
  75 percent of the model's window so a model swap does not silently change when
  compression fires.
- **`proactive_prune_tokens`** stubs old tool results before the summariser runs.
  Reclaiming tokens deterministically is cheaper than asking a model to do it.
- **`micro_compact_every_n_turns: 3`** amortises the auxiliary call. At every turn
  the summary latency lands on every turn.
- **`protect_first_n`** and **`protect_last_n`** keep the opening instructions and
  the live tail out of the summariser, which is where the answers usually are.
- **The auxiliary compression route** matters on a small or local model. Summaries
  are mechanical work, and routing them away from the main model keeps turn
  latency predictable.

A copy of this block ships as **[config.example.yaml](config.example.yaml)**.

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

## Re-vendoring the engine

The `jpm/` tree is vendored, not developed here. To update it:

```bash
rsync -a --delete \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='_OLD' \
  /path/to/upstream/core/jpm/ ./jpm/
```

Then re-run `./install.sh` and restart. Migrations apply on the next provider init.

---

## About the name

**MeAI Vault** is the product. `mea_pm` is the package it ships as, short for MEAI
permanent memory, and the name you will see in `memory.provider`, import paths and
plugin directories. The engine underneath is the vendored `jpm` tree.

Three names, one thing: permanent memory for your agent, kept in Postgres, shared
across every profile on the box.

---

## License

MIT. See [LICENSE](LICENSE).
