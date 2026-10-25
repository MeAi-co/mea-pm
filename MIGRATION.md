# Migrating from stock Hermes to the PG vault

This document is for anyone who already runs **stock Hermes** (SQLite) and is
installing the MEAI plugins. It explains what has to be configured, what the
schema does on first run, how to import your existing history, and how to
verify the result.

Read it before you run anything. The default state of a fresh install is a
**working plugin with an empty vault** — your existing conversation history is
invisible to every recall tool until you complete step 4.

---

## 0. The shape of the problem

Stock Hermes and the MEAI plugins store conversation in different places:

```
stock Hermes     $HERMES_HOME/state.db          SQLite, pruned at 90 days
MEAI plugins     PostgreSQL (JPM_PG_* env)     the vault
```

The `mea_sessions` plugin ships a `post_llm_call` mirror that copies each turn
from SQLite into PG **from the moment it is installed forward**. It has no
backfill. So:

- Turns after install → mirrored automatically. Nothing to do.
- Turns before install → **stay in SQLite forever** unless you run the
  migration script in step 4.

The two schemas have also drifted apart in both directions, so a naive
`INSERT ... SELECT *` will fail. The migration script projects an explicit
column list; see [Appendix A](#appendix-a--column-drift) for the exact diff.

---

## 1. Preflight — know what you have

Run these before changing anything. All read-only.

```bash
# Where is your stock database, and how big is it?
ls -lh "${HERMES_HOME:-$HOME/.hermes}/state.db"

# How much history is in it?
sqlite3 "${HERMES_HOME:-$HOME/.hermes}/state.db" \
  "SELECT 'sessions', COUNT(*) FROM sessions
   UNION ALL SELECT 'messages', COUNT(*) FROM messages;"
```

Write those two numbers down. They are your target for step 6.

If `state.db` does not exist, you have no history to migrate — skip to step 3.

---

## 2. Configuration — every flag, and the two traps

The engine reads PG connection settings from environment variables. Set them
in the **profile's `.env`**, never inline in `config.yaml`.

### Required

| Variable | Default | Notes |
|---|---|---|
| `JPM_PG_HOST` | *(none)* | **The only required variable.** |

### Optional

| Variable | Default | Notes |
|---|---|---|
| `JPM_PG_PORT` | `5432` | |
| `JPM_PG_DB` | `jpm` | |
| `JPM_PG_USER` | `postgres` | |
| `JPM_PG_PASSWORD` | `""` | Empty means "use `.pgpass` / peer auth". |

### Embeddings (optional — without these you get lexical search only)

| Variable | Default | Notes |
|---|---|---|
| `EMBED_PROVIDER` | `ollama` | |
| `EMBED_MODEL` | `nomic-embed-text` | |
| `EMBED_DIM` | `768` | Must match the model. |
| `OLLAMA_URL` | *(none)* | Any OpenAI-compatible endpoint. |
| `OLLAMA_FALLBACK_URL` | *(none)* | |
| `OLLAMA_API_KEY` | *(none)* | |

### Trap 1 — a missing `JPM_PG_HOST` fails silently

`is_pg_enabled()` returns `False` and the engine falls back to SQLite with a
`LOG.debug` line. At default log level you will see nothing. The plugin looks
installed and healthy while never touching PG.

**Check it explicitly:**

```bash
python3 -c "from jpm.core._pg import is_pg_enabled; print(is_pg_enabled())"
```

`True` means configured and reachable. `False` means `JPM_PG_HOST` is unset.

### Trap 2 — a set-but-unreachable host raises

If `JPM_PG_HOST` is set and PG cannot be reached, `is_pg_enabled()` raises
`RuntimeError`. There is no silent fallback in that case — by design. A typo'd
port is a hard failure at import, not a warning.

### Trap 3 — PostgreSQL needs the `vector` extension

`apply_schema()` runs `CREATE EXTENSION IF NOT EXISTS vector` and fails fast if
the extension is unavailable. Install `pgvector` before first start:

```bash
# Debian/Ubuntu
sudo apt install postgresql-16-pgvector
# Fedora
sudo dnf install pgvector
# or build from source: https://github.com/pgvector/pgvector
```

---

## 3. Schema — automatic, but only on a fresh database

You do **not** create tables by hand. `apply_schema()` in `jpm/core/_pg.py`
runs on first provider initialisation:

```
1. CREATE EXTENSION IF NOT EXISTS vector   (fail fast if unavailable)
2. If _schema_migrations is ABSENT  -> run _schema_pg.sql (the base schema)
3. Then run _migrations/*.sql in sorted order, recording each in
   _schema_migrations so it executes exactly once
4. If _schema_migrations is PRESENT -> SKIP the base schema entirely
```

**The consequence that matters:** the base schema only ever runs on a database
that has never been initialised. On an existing database, new objects arrive
only via numbered migrations. If you are upgrading an install that already has
`_schema_migrations`, the base schema will not re-run — that is correct and
intended.

**Start the agent once with the plugin enabled before migrating.** That is what
creates the tables the migration writes into. The migration script checks for
this and refuses to run if the schema is missing.

### Verify the schema landed

```bash
psql "$PG_URL" -c "\dt" | head -20
psql "$PG_URL" -c "SELECT COUNT(*) FROM _schema_migrations;"
```

The migration count should equal the number of `.sql` files in
`jpm/core/_migrations/`. Compare the two **sorted lists**, not just the counts —
equal counts can still hide a missing migration.

---

## 4. Data — import your existing history

The script is `jpm/scripts/migrate_from_stock.py`. It is:

- **dry-run by default** — writes nothing without `--apply`
- **idempotent** — `msg_key = md5(session_id || ':' || sqlite_row_id)`, the same
  formula the live mirror uses, so re-running is a no-op
- **resumable** — per-session floor is `MAX(message_id)` already in PG; only
  rows above the floor are read
- **read-only on the source** — SQLite is opened `mode=ro`; your stock install
  is never modified
- **path-free** — the SQLite file comes from `--state-db`, else
  `$HERMES_HOME/state.db`, else `~/.hermes/state.db`. Nothing is hardcoded.

### 4a. Dry run

```bash
cd <plugin dir>
python3 -m jpm.scripts.migrate_from_stock
```

Expected output:

```
source : /home/you/.hermes/state.db
target : PG ready
mode   : DRY RUN (nothing will be written)
source counts: {'sessions': 37, 'messages': 9200}
pg counts    : {'sessions': 144, 'messages': 24315}

sessions: seen=37 written=0 failed=0
  cols copied (42): id, source, user_id, model, ...
messages: seen=9200 written=0 failed=0
  cols copied (18): id, session_id, role, content, ...

Dry run complete. Re-run with --apply to write.
```

Check that `seen=` matches the counts from step 1. If `seen` is lower, some
sessions were filtered — investigate before applying.

### 4b. Apply

```bash
python3 -m jpm.scripts.migrate_from_stock --apply
```

Messages are written in batches of 500 per transaction. Use `--batch-size N` to
change that. A failure in one batch does not abort the run; failures are
collected and reported, and the exit code is `3`.

### 4c. Options

| Flag | Effect |
|---|---|
| `--state-db PATH` | Point at a non-default SQLite file. |
| `--apply` | Actually write. Without it, dry run. |
| `--verify` | Compare source vs PG counts and exit. |
| `--sessions-only` | Skip messages. |
| `--messages-only` | Skip sessions. |
| `--batch-size N` | Messages per transaction (default 500). |

### 4d. Exit codes

| Code | Meaning |
|---|---|
| `0` | Success, or dry run completed. |
| `1` | PG not configured, unreachable, or schema missing. |
| `2` | Source `state.db` missing or unreadable. |
| `3` | One or more rows failed — see the report. |

---

## 5. Identity files — NOT migrated

Stock keeps agent identity in flat files:

```
$HERMES_HOME/memories/SOUL.md
$HERMES_HOME/memories/MEMORY.md
$HERMES_HOME/memories/USER.md
```

The PG `knowledge` table has **no importer**. Even a perfect row copy in step 4
leaves the vault's knowledge section empty and the agent's identity still in
flat files.

This is deliberate for v0.1.0 — identity import needs a frontmatter parser and
a decision about how to map free-form markdown into typed knowledge rows. Until
then, the agent reads identity from the flat files as it always did, and the
vault holds conversation and skills only.

If you want identity in the vault, add entries manually:

```bash
python3 -c "
from jpm.core._write import _add_knowledge
_add_knowledge('identity', 'Agent name', 'What the agent is called.', 0.9)
"
```

---

## 6. Verify

Three independent layers. Do all three.

### Layer 1 — row counts

```bash
python3 -m jpm.scripts.migrate_from_stock --verify
```

`delta` should be `0` for both tables, or positive if PG already held rows from
the live mirror. A **negative** delta means rows are missing — re-run step 4b.

### Layer 2 — the plugin can read what you wrote

```bash
python3 -c "
from jpm.core._pg import sync_conn
with sync_conn() as c:
    print(c.fetchone('SELECT COUNT(*) AS n FROM messages'))
    print(c.fetchone('SELECT COUNT(*) AS n FROM sessions'))
"
```

### Layer 3 — a real recall query returns your history

```bash
python3 -c "
from jpm.core._search import _search_knowledge
rows, has_more = _search_knowledge('anything you actually said', limit=3, table='messages')
for r in rows:
    print(r.get('timestamp'), str(r.get('content'))[:80])
print('has_more:', has_more)
"
```

`_search_knowledge(query, limit=10, offset=0, table='knowledge')` returns a
`(results, has_more)` tuple. `table='messages'` is the one you want here; the
default is `knowledge`.

For semantic (vector) recall instead of lexical, use `hybrid_message_ids`:

```bash
python3 -c "
from jpm.core._hybrid_search import hybrid_message_ids
ids, used_vectors = hybrid_message_ids('anything you actually said', limit=5)
print('ids:', ids, 'vector_path_used:', used_vectors)
"
```

It returns `(ids, used_vectors)`. `used_vectors=False` means embeddings were
unavailable and it fell back to FTS — rows are still findable, just lexically.

If layer 1 passes but layer 3 returns nothing, the rows are there but not
searchable — check that `search_vector` is populated (it is a generated column,
so it fills automatically) and that embeddings were generated if you are using
semantic search.

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `is_pg_enabled()` returns `False` | `JPM_PG_HOST` unset | Set it in the profile `.env`. |
| `RuntimeError` at import | Host set, PG unreachable | Check host/port; confirm PG is listening. |
| `schema file not found` | `.sql` files not in the repo | See [Appendix B](#appendix-b--the-gitignore-trap). |
| `column "..." does not exist` | Schema drift, migration not run | Restart the gateway so `apply_schema()` runs. |
| Migration says `PG NOT READY` | Schema missing | Start the agent once with the plugin enabled. |
| `seen=0` in dry run | Wrong `state.db` | Pass `--state-db` explicitly. |
| Rows written but recall empty | Embeddings not generated | Check `OLLAMA_URL`; lexical search still works. |

---

## Appendix A — column drift

The two schemas are not the same shape. Measured on a live install:

```
messages    SQLite 30 cols  ->  PG 22 cols (base schema)
sessions    SQLite 62 cols  ->  PG 52 cols (base schema)
```

**Dropped on the way in** (present in SQLite, absent from PG — the migration
skips these):

```
messages   _compressed_summary, absorbed_message_uids, api_content,
           display_identity, display_kind, display_metadata, display_order,
           effect_disposition, message_uid, reasoning, tool_call_uid,
           tool_call_uids

sessions   auto_archived, compression_failure_cooldown_until,
           compression_failure_error, compression_fallback_streak,
           compression_ineffective_count, compression_overload_streak,
           compression_recovery_deadline, created_source,
           git_metadata_generation, hidden, last_activity_at,
           last_activity_description, last_activity_provenance,
           last_read_at, pinned, profile_name, system_prompt_hash,
           title_source, tool_names, transport_profile
```

**Added by PG** (absent from SQLite — filled by column defaults):

```
messages   agent_compacted, flow_summarized_at, message_id, msg_key,
           content_hash, search_vector

sessions   auto_reset_reason, is_fresh_reset, last_processed_msg_id,
           last_prompt_tokens, last_resume_marked_at, reset_had_activity,
           resume_pending, resume_reason, suspended, was_auto_reset
```

The migration copies **42 session columns and 18 message columns** — the
intersection of both sides. Every projected column was verified present in PG
before shipping.

---

## Appendix B — the `.gitignore` trap

A blanket `*.sql` rule in `.gitignore` ships a repository that **cannot create a
single table**. The files exist on disk, `git status` is clean, and the repo
looks complete.

```bash
git ls-files '*.sql' | wc -l     # 0
find . -name '*.sql' | wc -l    # 65
```

If those two numbers disagree, the base schema and every migration are
untracked. A fresh clone fails at `apply_schema()` with "schema file not found"
before it can create one table.

The fix is to replace `*.sql` with targeted dump rules:

```gitignore
*.dump
*.sql.gz
*.sql.bak
# NOTE: *.sql is deliberately NOT ignored. The base schema (_schema_pg.sql)
# and every file in _migrations/ are SOURCE, not dumps.
```

---

## Appendix C — what the migration does not do

- **Does not touch your stock install.** SQLite is opened read-only.
- **Does not delete anything in PG.** Inserts only; conflicts are ignored.
- **Does not migrate identity files.** See step 5.
- **Does not migrate skills.** Skills live in `$HERMES_HOME/skills/` and are
  imported by the `mea_skills` plugin, not by this script.
- **Does not generate embeddings.** Rows land with `embedding = NULL`; the
  embed worker fills them on its next pass if `OLLAMA_URL` is configured.
- **Does not run the schema.** Start the agent once first (step 3).
