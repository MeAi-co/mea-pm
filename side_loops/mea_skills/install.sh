#!/usr/bin/env bash
# mea_skills install — tracked, idempotent. Installs the vendored engine's
# runtime deps into the stock Hermes runtime interpreter and verifies the
# plugin loads and all four skill tools register.
#
# Usage:  ./install.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 1. Resolve the stock runtime interpreter ────────────────────────────────
# The runtime interpreter lives under the BASE home ($HOME/.hermes/tools/...),
# NOT under the profile home. Resolve it from the base home explicitly.
BASE_HOME="${HERMES_BASE_HOME:-$HOME/.hermes}"
PY="$(ls -d "${BASE_HOME}"/tools/python-*/bin/python3 2>/dev/null | head -1 || true)"
if [[ -z "${PY}" ]]; then
  echo "ERROR: could not find the Hermes runtime python under ${BASE_HOME}/tools/python-*/bin/" >&2
  exit 1
fi
echo "runtime python: ${PY}"
"${PY}" --version

# ── 2. Install deps ──────────────────────────────────────────────────────────
# ruamel.yaml is required by hermes_cli.config itself (the loader imports it
# before any plugin loads). asyncpg/psycopg2/pyyaml are the engine's deps.
DEPS=(ruamel.yaml asyncpg psycopg2-binary pyyaml)
echo "installing: ${DEPS[*]}"
"${PY}" -m pip install --disable-pip-version-check --no-input "${DEPS[@]}"

# ── 3. Verify imports ─────────────────────────────────────────────────────────
echo "verifying imports..."
"${PY}" - <<'PYEOF'
import importlib, sys
missing = []
for m in ("ruamel.yaml", "asyncpg", "psycopg2", "yaml"):
    try:
        importlib.import_module(m)
        print(f"  OK   {m}")
    except Exception as e:
        missing.append(f"{m}: {e}")
        print(f"  FAIL {m}: {e}")
if missing:
    sys.exit("missing deps: " + "; ".join(missing))
print("all deps present")
PYEOF

# ── 4. Verify the plugin loads and all four tools register ──────────────────
# The plugin lives at <profile_home>/plugins/mea_skills, so the profile home is
# two levels up. Point HERMES_HOME at THIS profile — not the base home.
PROFILE_HOME="$(cd "${HERE}/../.." && pwd)"
# The stock CODE tree (hermes_cli/, tools/) lives at the BASE home, not the
# profile home. Resolve it: prefer $HERMES_CODE, else <base>/hermes-agent.
CODE_DIR="${HERMES_CODE:-${BASE_HOME}/hermes-agent}"
if [[ ! -d "${CODE_DIR}/hermes_cli" ]]; then
  echo "ERROR: stock code tree not found at ${CODE_DIR} (set HERMES_CODE)" >&2
  exit 1
fi
echo "verifying plugin load (HERMES_HOME=${PROFILE_HOME}, CODE=${CODE_DIR})..."
HERMES_HOME="${PROFILE_HOME}" "${PY}" - <<PYEOF
import sys
sys.path.insert(0, "${CODE_DIR}")
from hermes_cli.plugins import discover_plugins
from tools.registry import registry
discover_plugins(force=True)
for name in ("skills_list", "skill_view", "skill_manage", "skill_choose"):
    entry = registry.get_entry(name)
    if entry is None:
        sys.exit(f"{name} tool did not register")
    print(f"  registered: {name} (toolset={entry.toolset}, emoji={entry.emoji!r})")
PYEOF

echo "mea_skills install complete."
