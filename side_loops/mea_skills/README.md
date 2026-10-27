# mea_skills: MEAI Skills

Stock-Hermes plugin exposing the MEAI skill toolset. Ports the Joshaico fork's
skill tools onto stock Hermes **without touching the stock tree**, so
`git pull` / auto-update cannot clobber them.

## Tools

| Tool | Kind | Notes |
|---|---|---|
| `skills_list` | **override** | PG-backed catalog + role tags + plugin-namespace dispatch |
| `skill_view` | **override** | PG body fetch, section filter, view/use telemetry bump |
| `skill_manage` | **override** | PG dual-write, guard scan, write-approval gate |
| `skill_choose` | **new** | Ranked catalog + section-level retrieval (no stock equivalent) |

The three overrides need the operator grant
`plugins.entries.mea_skills.allow_tool_override: true`. `skill_choose` is a pure
addition and needs no grant.

## Layout

```
mea_skills/
├── __init__.py            # register(ctx): registers the 4 tools
├── _shims.py              # aliases fork-only imports onto stock modules
├── _skills_tool.py        # vendored fork skills_tool.py (registration tail stripped)
├── _skill_manager_tool.py # vendored fork skill_manager_tool.py (tail stripped)
├── _skill_choose_tool.py  # vendored fork skill_choose_tool.py (tail stripped)
├── jpm/                   # vendored engine (PG access, sections, embeddings)
├── plugin.yaml            # manifest (name: mea-skills)
├── install.sh             # tracked, idempotent install + verify
└── README.md
```

## Install

```bash
./install.sh
```

The script:
1. Resolves the stock runtime interpreter from the **base** home
   (`$HOME/.hermes/tools/python-*/bin/python3`), not the profile home.
2. Installs deps (`ruamel.yaml`, `asyncpg`, `psycopg2-binary`, `pyyaml`) into it.
3. Verifies the imports.
4. Loads the plugin in a fresh process and asserts all four tools register.

## Enable

The plugin is **opt-in**. Add its manifest key (hyphenated, `mea-skills`) to the
profile `config.yaml`:

```yaml
plugins:
  enabled:
    - mea-skills
  entries:
    mea_skills:
      allow_tool_override: true
```

Both `plugins.enabled` and `plugins.entries` are keyed by the **manifest key**
(`mea-skills`, hyphen), the loader sets `plugin_id = manifest_key(manifest)`
(`plugins_loader.py`), and `manifest_key` is the path-derived key, which for a
flat plugin dir equals the manifest `name:`. The **directory name**
(`mea_skills`, underscore) is never used as the config key.

## How the fork-only imports are handled

The vendored tool modules were lifted from the fork and import names that do not
exist in stock Hermes. `_shims.install()` (called before the vendored modules are
imported) installs alias modules into `sys.modules`:

| Fork import | Stock target |
|---|---|
| `joshaico_constants` | `hermes_constants` (`get_hermes_home`, `display_hermes_home`, `get_default_hermes_root`) |
| `joshaico_constants.load_role_bundles` | stub returning `{}` (roles are a fork feature) |
| `joshaico_cli.config` | `hermes_cli.config` (`cfg_get`, `load_config`) |
| `joshaico_cli.plugins` | `hermes_cli.plugins` (`_get_disabled_plugins`, `get_plugin_manager`, `discover_plugins`) |
| `tools.role_choose_tool._current_role` | stub returning `None` |

The vendored sources are **not edited**, the shims make them run unmodified.

## Load order (why `override=True` wins)

`model_tools.py` runs `discover_builtin_tools()` (line 149) **before**
`discover_plugins()` (line 162). Built-ins register first, then the plugin
registers with `override=True` and replaces them.

## Pitfalls

1. **`plugins.enabled` uses the manifest key (`mea-skills`), not the dir name
   (`mea_skills`).** Listing the wrong one silently skips the plugin.
2. **The override grant is keyed by the manifest key (`mea-skills`, hyphen),
   not the directory name (`mea_skills`).** Without it,
   `register_tool(..., override=True)` raises `PluginToolOverrideError`.
3. **The runtime interpreter lives under the base home**, not the profile.
4. **`config.yaml` is guard-protected**, edit it with an anchored text replace,
   not `patch`/`write_file`.
