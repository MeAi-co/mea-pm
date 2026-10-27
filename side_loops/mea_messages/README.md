# mea_messages — MEAI Messages

The **`messages`** tool: message-level recall across all past sessions,
exposed from the vendored `jpm` engine as a stock-Hermes plugin.

## What it is

A thin wrapper that registers the engine's message-recall function under the
bare tool name **`messages`**. The model sees `messages`, never `mea_messages`
— the `mea_` prefix lives on the plugin directory only.

| Layer | Value |
|---|---|
| Plugin dir | `mea_messages` (underscore — valid Python identifier) |
| Manifest name | `mea-messages` |
| Tool (model-facing) | `messages` |
| Toolset | `session_search` |
| Emoji | 💬 |

Stock Hermes has **no** `messages` tool (only `session_search`), so this is a
**pure addition** — no `override=True`, no operator grant required.

## Install

```bash
./install.sh
```

Tracked and idempotent. It:
1. resolves the stock runtime interpreter (`$HERMES_HOME/tools/python-*/bin/python3`),
2. installs the engine's runtime deps (`ruamel.yaml asyncpg psycopg2-binary pyyaml`),
3. verifies the imports,
4. verifies the plugin loads and `messages` registers.

## Activate

`mea_messages` is a `standalone` plugin — it must be listed in the profile's
`config.yaml` **by its manifest key** (`mea-messages`, hyphen — NOT the dir
name):

```yaml
plugins:
  enabled:
    - mea-messages
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
mea_messages/
├── __init__.py         # register(ctx) -> ctx.register_tool("messages", ...)
├── _messages_tool.py   # vendored tool logic (stock registry tail stripped)
├── plugin.yaml         # manifest
├── install.sh          # tracked, idempotent install + verify
├── README.md           # this file
└── jpm/                # vendored engine (absolute jpm.* self-imports)
```
