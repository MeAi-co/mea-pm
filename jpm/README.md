# JPM — Workhorse Memory

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
| `__init__.py` | Main plugin code — hooks, tool, YAML builder |
| `scripts/backfill.py` | Optional seed script (see below) |

## Installation

1. Copy the `jpm` folder to the target agent's `~/.joshaico/plugins/` directory
2. Add `jpm` to `plugins.enabled` in `config.yaml`
3. Restart the gateway

## Backfill (optional)

`scripts/backfill.py` seeds the tables with historical context from conversation history. **This is a suggestion, not a requirement.** The agent should review, prune, and add what fits their own context.

To run:
```bash
python3 /path/to/jpm/scripts/backfill.py
```

The script is safe to run multiple times — it uses INSERT OR IGNORE for knowledge entries and won't duplicate data.

## Usage

The unified `jpm` tool supports these actions:

- `fetch` — `section=pulse|active|loops|knowledge|reflections|capabilities|task_context`
- `update` — `section=pulse content=status:blocked summary:API rate limited`
- `add` — `category=project content=type:system name:redis description:used for session cache`
- `search` — `query=full text search`
- `probe` — `entity=MySystem`
- `related` — `entity=MySystem`
- `reason` — `entities=["A","B"]`
- `helpful` / `unhelpful` — `fact_id=123`

## YAML Injection

On first turn of each session, JPM injects a compact block with:
- Current status (pulse)
- Active focus and project
- Open loops (top 5 by priority)
- Known systems (top 3)
- Project milestones

No fluff. Just what a dev agent needs to pick up where they left off.
