# MeAI Vault™

**Permanent memory for stock Hermes agents.**

Your agent forgets everything the moment the window closes. Not just the facts you
told it: the rules you spent a week tuning, the project it was halfway through, the
preference you corrected twice. Close a tab, start a new task, come back after
lunch, and it greets you as a stranger. Then the first ten turns of every session
go into getting it back to where it already was.

MeAI Vault ends that. It gives a stock Hermes agent permanent memory: conversations,
facts, rules, preferences, entities, reflections and skills stored as rows in
Postgres, vectorised so recall works by meaning instead of exact wording. Close the
window, restart the gateway, compact the context, open a different topic on a
different profile three weeks later. The agent keeps the same brain.

**What it is.** A PostgreSQL-backed memory provider for stock Hermes. One store for
the whole box, not one file per profile. Every chat, topic, cron job and profile
reads and writes the same rows. No fork, no core patches, no upstream update to
chase.

**The part no other memory plugin does.** The schema is not fixed. The agent can
create its own tables, add columns, index them, and query them with raw SQL, so a
watchlist, a fleet charter, a trade ledger or a project tracker all live in the same
brain as its rules and its history. It is a small PG admin console for the agent,
pointed at its own memory.

**Why it exists.** Because a memory plugin that lives in a file the agent has to be
reminded to open is a coin toss in practice. We watched agents store the right fact
and then fail to find it, store it and look it up under a different string, deny the
store existed until challenged, and come back from compaction with no idea what they
were doing. So we built the version where the store is the authority, the tools sit
on the surface instead of behind a search box, and the agent reaches for them
without being prompted.

**How it differs from standard memory plugins.** They are fact stores the agent
consults when probed, and they answer out of whatever happened to be injected into
the prompt. MeAI Vault is read and written by the agent as part of the turn,
retrieves with vector and full text together, survives compaction because the rows
were never in the prompt to begin with, and hands the agent SQL access to its own
memory for when it needs to audit instead of recall.

**The verdict.** Six live tests, user and agent in the same loop, the same seeded
history on both sides, this stack against stock Hermes plus Mnemosyne. This stack
took five of the six. The one it lost went narrowly to the other stack on a
deliberately isolated axis, provenance separation: the other stack traced a thread
back to its source and said plainly it was not the user's, while this stack revised
a total mid answer without flagging that the earlier figure had just been withdrawn.
The runs are reported one at a time and are not averaged into a total, because the
questions were vague on purpose and a single run only proves what its own axis
measures. What held constant across all six was how this stack operates: its tools,
its context envelope and its retrieval habit never changed, so its wrong answers
tracked how vague the question was rather than instability in the stack. The other
stack hedged, refused, corrected itself only after a push, and in one run went
around its own tools to read the database file directly. Reports, chat logs and agent
logs are in [`bench/`](bench/README.md).

It is the assistant memory we wanted for our own daily work. That is why we built
it, and why we are giving it away.

---

---

**On this page:** [The short version](#the-short-version) · [Who it is for](#who-it-is-for) · [Requirements](#requirements) · [Quickstart](#quickstart) · [Configuration you can start from](#reference-configuration) · [Memory the agent actually uses](#memory-the-agent-actually-uses) · [Why flat memory stops working](#why-flat-memory-stops-working) · [A central Postgres store beats a local memory plugin](#a-central-postgres-store-beats-a-local-memory-plugin) · [`vault` is an admin console, not a lookup](#vault-is-an-admin-console-not-a-lookup) · [The agent builds its own schema](#the-agent-builds-its-own-schema) · [One box, many agents, many topics](#one-box-many-agents-many-topics) · [Architecture](#architecture) · [Coming from stock Hermes](#coming-from-stock-hermes) · [Side loops](#side-loops) · [Evaluation](#evaluation) · [Re-vendoring the engine](#re-vendoring-the-engine) · [About the name](#about-the-name) · [License](#license)

## The short version
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

## `vault` is an admin console, not a lookup

A memory plugin gives the agent one verb: recall. `vault` gives it the database and
the rights to run it. Twenty actions, and they are not a menu of conveniences, they
are four jobs that a memory tool cannot do.

**1. Recall well.** `search` (vector first, full text as fallback), `fetch`
(structured sections: pulse, active, loops, knowledge, reflections, capabilities,
task context), `get` and `row` (one record in full, by id), `list` (recent entries).
This is the only part that resembles a normal memory plugin, and it is the smallest
part.

**2. Reason over the graph.** `probe` (everything linked to one entity), `related`
(facts sharing entities), `reason` (facts connected to several entities at once),
`contradict` (entries that disagree). A flat file cannot do any of this. It is how an
agent discovers that two facts are about the same person, or that the store holds two
versions of the same decision and one of them has to lose.

**3. Curate the memory.** `add`, `update`, `remove`, `helpful`, `unhelpful`. Every
fact carries a weight, and feedback moves it. An entry that keeps proving useful gets
injected in full; one that keeps proving stale drops to a breadcrumb and eventually
out of the prompt while staying searchable. The agent manages its own signal to noise
instead of accumulating forever.

**4. Administer the store.** `tables`, `schema`, `query`, `row`, `create_table`,
`rename_table`, `index`. This is the group that changes what the thing is. The agent
can read its own schema when a query fails, build a table for work that has structure,
and ask questions of its memory that no recall call can answer. The first two run
against the core schema as shipped; the third assumes a table the agent made for
itself:

```python
# which entries are injected into every prompt but never actually used?
vault(action='query', sql="""SELECT name, retrieval_count, weightage
    FROM knowledge WHERE weightage >= 0.70 AND retrieval_count = 0
    ORDER BY weightage DESC""")

# what is stored but not yet searchable by meaning?
vault(action='query', sql="""SELECT entity_type, count(*) FROM knowledge
    WHERE embedding IS NULL GROUP BY 1 ORDER BY 2 DESC""")

# cross the agent's own table with the facts it decided to keep
vault(action='query', sql="""SELECT w.symbol, w.target, k.name FROM watchlist w
    JOIN knowledge k ON k.name ILIKE '%' || w.symbol || '%'""")
```

Those three questions are a small sample of a different class of question. Not "what
do you remember about me", but "is my memory healthy", "what is costing prompt space
without earning it", "what never got embedded", "how does what I track line up with
what I know".

The same interface serves memory, history, skills and the agent's own tables, with the
connection handled inside the plugin so no credentials ever enter the conversation.
That is what separates an admin console from a lookup: one answers a question, the
other lets the agent keep the whole system in shape.

---

## The agent builds its own schema

This is the difference that is hard to overstate. Every other memory plugin hands the
agent a fixed shape: a note, a fact, a document, a vector. If your data does not fit,
it goes in a text blob and the structure is lost.

MeAI Vault hands the agent a database. It can create tables, describe them, index
them, rename them and query them, which means the store grows to fit the work instead
of the work being flattened to fit the store.

```python
# a table that did not exist five seconds ago
vault(action='create_table', name='watchlist',
      columns=['symbol text not null', 'target numeric', 'note text'])

# write to it, no migration, no config change
vault(action='query', sql="INSERT INTO watchlist (symbol, target) VALUES ('NVDA', 180)")

# read it back with whatever predicate the question needs
vault(action='query', sql="SELECT symbol, target FROM watchlist WHERE target > 170")

# inspect the shape, add an index when the table grows
vault(action='schema', table='watchlist')
vault(action='index', op='create', name='idx_watchlist_symbol',
      table='watchlist', columns=['symbol'])
```

What happens underneath:

- **Every new table gets an `id` primary key and a `timestamp` column** unless you
  declare them, because that is what an agent assumes exists when it later writes
  `WHERE id = ...` or sorts by time.
- **User tables are physically named `user_<name>`** so they never mix with core
  tables, while the agent keeps using the bare name. The rewrite is transparent, so
  no query or script ever has to know about the prefix.
- **Raw SQL is accepted** when the column helper is not enough: `create_table` takes
  an `sql=` argument and runs the DDL as written.
- **Guards hold.** Destructive statements against core tables are hard blocked, and
  against a table the agent created they need an explicit `confirm=true`. A single
  bad query cannot wipe the memory it was supposed to be maintaining.

The practical result: a watchlist, a fleet charter, a trade ledger, a reading list, a
client roster and a project tracker can all live beside the agent's rules, history and
skills, in the same store, queryable with SQL, backed up with one `pg_dump`. The agent
administers its own memory instead of borrowing a corner of someone else's schema.

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
| `mea_loop_skillnudge` | injects synthetic load and maintenance directives so the agent pulls the right skill itself, re-arming across multi loop turns (capped per turn) |
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

Each run is reported on its own axis and the results do not agree across the block:
this stack won the first two, lost the third narrowly on provenance, and won the last
three. They are not a trend line and they are not averaged into a total. What the
reports do establish, read together, is that this stack's tools, context envelope and
retrieval habit did not change from the first run to the last. See `bench/README.md`
for the method, the arm definitions, and the transcripts behind each result.

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

The engine is why the tool is called `vault` and why its actions still read as `jpm`
in the logs. In practice: call it MeAI Vault in conversation, `mea_pm` when you touch
config, and ignore `jpm` unless you are reading the engine's own output.

---

## License

MIT. See [LICENSE](LICENSE).
