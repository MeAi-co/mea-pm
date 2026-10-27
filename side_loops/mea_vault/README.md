# mea_vault — MEAI Vault

The **`vault`** tool: PG-backed memory + schema/SQL access, exposed from the
vendored `jpm` engine as a stock-Hermes plugin.

## What it is

A thin wrapper that registers the engine's unified dispatcher under the bare
tool name **`vault`**. The model sees `vault`, never `mea_vault` — the `mea_`
prefix lives on the plugin directory only.

| Layer | Value |
|---|---|
| Plugin dir | `mea_vault` (underscore — valid Python identifier) |
| Manifest name | `mea-vault` |
| Tool (model-facing) | `vault` |
| Toolset | `vault` |
| Emoji | 🤖 |

## Install

```bash
./install.sh
```

Tracked and idempotent. It:
1. resolves the stock runtime interpreter (`$HERMES_HOME/tools/python-*/bin/python3`),
2. installs the engine's runtime deps (`ruamel.yaml asyncpg psycopg2-binary pyyaml`),
3. verifies the imports,
4. verifies the plugin loads and `vault` registers.

## Activate

`mea_vault` is a `standalone` plugin — it must be listed in the profile's
`config.yaml` **by its manifest key** (`mea-vault`, hyphen — NOT the dir name):

```yaml
plugins:
  enabled:
    - mea-vault
```

## Config

PG connection comes from the profile `.env` (never inline in `config.yaml`):

```
JPM_PG_HOST=...
JPM_PG_PORT=...
JPM_PG_DB=...
JPM_PG_USER=...
JPM_PG_PASSWORD=...
```

## Layout

```
mea_vault/
├── __init__.py     # register(ctx) -> ctx.register_tool("vault", ...)
├── plugin.yaml     # manifest
├── install.sh      # tracked install + verify
├── README.md       # this file
└── jpm/            # vendored engine (untouched; absolute jpm.* self-imports)
```

## Notes

- The engine is vendored **unchanged** so its absolute `from jpm.core...`
  self-imports resolve. `__init__.py` inserts the plugin dir at `sys.path[0]`.
- No core file is touched. A stock auto-update / `git pull` cannot clobber this.
- The progress bubble renders `🤖 vault: "…"` for free — the raw tool name is
  the label when no curated verb exists.
