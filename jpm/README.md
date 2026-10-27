# JPM: Workhorse Memory

Stripped-down persistent memory for development agents. No personality tracking, no emotional fluff, no small talk. Pure project context.

## Schema

| Table | Purpose |
|-------|---------|
| `pulse` | Project status snapshots (nominal, blocked, degraded, idle) |
| `active` | Current focus and project |
| `loops` | Open dev issues, bugs, todos (with priority and project tags) |
| `knowledge` | Systems, configs, architecture, dependencies |
| `reflections` | Technical lessons learned |
| `capabilities` | Tool proficiency tracking |
| `task_context` | Project milestones and deployment status |

## What it doesn't have

- No traits schema (no personality tracking)
- No topics schema (no personal interests)
- No small talk (no conversation threading)
- No user model (no style preferences)
- No growth log (no personal growth)
- No adaptation log (no behavioral changes)

## Files

| File | Purpose |
|------|---------|
| `plugin.yaml` | Plugin manifest |
| `__init__.py` | Main plugin code, hooks, tool, YAML builder |
| `scripts/migrate_from_stock.py` | Import stock Hermes history into PG (see below) |

## Installation

1. Copy the `jpm` folder to the target agent's `$HERMES_HOME/plugins/` directory
2. Add `jpm` to `plugins.enabled` in `config.yaml`
3. Restart the gateway

## Migrating existing history (optional)

`scripts/migrate_from_stock.py` imports an existing stock Hermes SQLite
`state.db` into the PG tables. It is **dry-run by default**, nothing is written
until you pass `--apply`.

```bash
python3 /path/to/jpm/scripts/migrate_from_stock.py            # preview
python3 /path/to/jpm/scripts/migrate_from_stock.py --apply    # write
python3 /path/to/jpm/scripts/migrate_from_stock.py --verify   # check
```

The source path resolves from `--state-db`, else `$HERMES_HOME/state.db`, else
`~/.hermes/state.db`. Nothing is hardcoded. The import is idempotent and
resumable, re-running only inserts what is missing. See `MIGRATION.md` at the
repo root for the full procedure, the column mapping, and the known gaps.

## Usage

The unified `jpm` tool supports these actions:

- `fetch`, `section=pulse|active|loops|knowledge|reflections|capabilities|task_context`
- `update`, `section=pulse content=status:blocked summary:API rate limited`
- `add`, `category=project content=type:system name:redis description:used for session cache`
- `search`, `query=full text search`
- `probe`, `entity=MySystem`
- `related`, `entity=MySystem`
- `reason`, `entities=["A","B"]`
- `helpful` / `unhelpful`, `fact_id=123`

## YAML Injection

On first turn of each session, JPM injects a compact block with:
- Current status (pulse)
- Active focus and project
- Open loops (top 5 by priority)
- Known systems (top 3)
- Project milestones

No fluff. Just what a dev agent needs to pick up where they left off.
