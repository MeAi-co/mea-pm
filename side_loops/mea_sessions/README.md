# mea_sessions — MEAI Sessions

The **`sessions`** tool: PG-backed session recall for stock Hermes, forked from
the Joshaico fork's `session_search` and retargeted at the MEAI PostgreSQL
memory store. FTS over `messages.search_vector` plus a pgvector semantic-recall
fallback, deduped by session lineage, ranked newest-first.

It also **disables the stock `session_search`** so the model sees one recall
tool, not two.

## What it does

| Shape | Call | Returns |
|---|---|---|
| Discovery | `sessions(query="auth refactor", limit=3)` | FTS + vector hits, deduped by lineage; each with snippet, ±5 window, bookends, message_count |
| Scroll | `sessions(session_id="…", around_message_id=12345, window=10)` | ±window slice around the anchor |
| Read | `sessions(session_id="…")` | Whole-session dump (first 20 + last 10) |
| Browse | `sessions()` | Recent sessions chronologically |

## Install

```bash
cd ~/.hermes/profiles/<profile>/plugins/mea_sessions
./install.sh
```

`install.sh` is the single tracked install path. It:
1. resolves the stock runtime interpreter (`$HERMES_HOME/tools/python-*/bin/python3`),
2. installs `ruamel.yaml asyncpg psycopg2-binary pyyaml` into it,
3. verifies the imports,
4. verifies the plugin loads, `sessions` registers, and `session_search` is gone.

## Activate

Two config edits in the profile's `config.yaml`:

```yaml
plugins:
  enabled:
    - mea-sessions          # the manifest KEY (name:), NOT the dir name
  entries:
    mea_sessions:           # the plugin_id (dir name) for the override grant
      allow_tool_override: true
```

- `plugins.enabled` matches the manifest **key** (`mea-sessions`, hyphen).
- The override grant key is the **plugin_id** (`mea_sessions`, underscore) —
  required because the plugin deregisters the built-in `session_search`.

PG credentials live in the profile `.env` (`JPM_PG_HOST`, `JPM_PG_PORT`,
`JPM_PG_DB`, `JPM_PG_USER`, `JPM_PG_PASSWORD`).

## Layout

```
mea_sessions/
├── __init__.py         # register(ctx): register `sessions` + disable `session_search`
├── _sessions_tool.py   # vendored tool logic (PG-backed, no registry tail)
├── plugin.yaml         # name: mea-sessions, kind: standalone, provides_tools: [sessions]
├── install.sh          # tracked, idempotent install + verify
├── README.md           # this file
└── jpm/                # vendored engine (absolute jpm.* self-imports)
```

## Notes

- **Plugin-only.** No file under the stock tree (`~/.hermes/hermes-agent/`) is
  edited. The legacy tool is removed at runtime from the plugin's `register(ctx)`,
  so `git pull` / auto-update cannot clobber it.
- The vendored engine keeps the inner package name `jpm` so its absolute
  `from jpm.core...` self-imports resolve.
