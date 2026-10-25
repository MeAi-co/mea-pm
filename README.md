# mea_pm - MEAI Persistent Memory

PG-backed permanent memory provider for stock Hermes. Thin wrapper around the vendored
`jpm` engine. No core modifications - it plugs into the stock memory-provider seam.

## Layout

```
mea_pm/
├── __init__.py     # register(ctx) → ctx.register_memory_provider(...)
├── plugin.yaml     # manifest: name, kind, python_dependencies, requires_env
├── install.sh      # tracked install (deps + activation)
├── README.md       # this file
└── jpm/            # vendored engine (do not edit; re-vendor from the fork)
```

## How it loads (stock contract)

`plugins/memory/__init__.py` discovers a provider dir when its `__init__.py`
mentions `register_memory_provider` or `MemoryProvider` in the first 8 KB (or
defines a `MemoryProvider` subclass). It then imports the package under a
synthetic namespace and calls `register(ctx)`; `ctx.register_memory_provider()`
captures the instance. **No core edit is required.**

The vendored engine has 8 absolute `from jpm.core...` self-imports, so
`__init__.py` inserts the plugin dir at `sys.path[0]` to make `jpm` a
top-level importable name.

## Dependencies

Declared in `plugin.yaml` under `python_dependencies` (validated + surfaced by
the manifest reader; **never auto-installed**). The stock runtime ships an
isolated Python with an empty site-packages, so these must be installed:

| Package | Why |
|---|---|
| `asyncpg` | PG pool (primary driver in `jpm/core/_pg.py`) |
| `psycopg2-binary` | PG reachability probe (`is_pg_enabled`) |
| `pyyaml` | config + YAML injection payload |

> Note: the stock runtime also needs `ruamel.yaml` for `hermes_cli.config`
> itself to import — without it the loader cannot even start. See install.sh.

## Install

```bash
cd <this dir>
./install.sh
```

`install.sh` is idempotent and prints each step. It installs the deps into the
runtime interpreter and verifies the import.

## Activate

In the target profile's `config.yaml`:

```yaml
memory:
  provider: mea_pm
```

Then restart the gateway (or start a new session).

## Environment

| Var | Required | Default |
|---|---|---|
| `JPM_PG_HOST` | yes | — |
| `JPM_PG_PORT` | no | 5432 |
| `JPM_PG_DB` | no | jpm |
| `JPM_PG_USER` | no | postgres |
| `JPM_PG_PASSWORD` | no | (empty / .pgpass) |

Set these in the profile's `.env` (secrets) — never inline in config.yaml.

## Re-vendoring

```bash
rsync -a --delete \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='_OLD' \
  /path/to/upstream/core/jpm/ ./jpm/
```
