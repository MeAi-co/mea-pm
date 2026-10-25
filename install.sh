#!/usr/bin/env bash
# mea_pm install — tracked, idempotent. Installs the vendored engine's runtime
# deps into the stock Hermes runtime interpreter and verifies the import.
#
# Usage:  ./install.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 1. Resolve the stock runtime interpreter ────────────────────────────────
# The runtime python is NOT always under $HERMES_HOME. On a packaged install it
# sits beside the code tree (e.g. <base>/tools/python-*/bin/python3) while
# HERMES_HOME points at the profile. Probe every plausible location, in order,
# and let the caller override with HERMES_PYTHON.
BASE_HOME="${HERMES_BASE_HOME:-$HOME/.hermes}"
CODE_DIR="${HERMES_CODE:-${BASE_HOME}/hermes-agent}"

find_py() {
  local d
  for d in \
      "${HERMES_PYTHON:-}" \
      "${HERMES_HOME:-$HOME/.hermes}"/tools/python-*/bin/python3 \
      "${BASE_HOME}"/tools/python-*/bin/python3 \
      "$(dirname "${CODE_DIR}")"/tools/python-*/bin/python3 \
      "${CODE_DIR}"/tools/python-*/bin/python3 ; do
    [[ -n "$d" && -x "$d" ]] && { echo "$d"; return 0; }
  done
  return 1
}

PY="$(find_py || true)"
if [[ -z "${PY}" ]]; then
  echo "ERROR: could not find the Hermes runtime python." >&2
  echo "       Probed: \$HERMES_PYTHON, \$HERMES_HOME/tools, \$HERMES_BASE_HOME/tools," >&2
  echo "               <code-tree>/../tools, <code-tree>/tools" >&2
  echo "       Set HERMES_PYTHON=/path/to/python3 and re-run." >&2
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

# ── 3. Verify ────────────────────────────────────────────────────────────────
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

# ── 4. Verify the plugin loads under the stock loader ────────────────────────
# The plugin lives at <profile_home>/plugins/mea_pm, so the profile home is two
# levels up. The loader resolves user plugins from $HERMES_HOME/plugins, so we
# must point HERMES_HOME at THIS profile — not the base home.
PROFILE_HOME="$(cd "${HERE}/../.." && pwd)"
# The stock CODE tree (hermes_cli/, tools/) lives at the BASE home, not the
# profile home. Resolve it: prefer $HERMES_CODE, else <base>/hermes-agent.
BASE_HOME="${HERMES_BASE_HOME:-$HOME/.hermes}"
CODE_DIR="${HERMES_CODE:-${BASE_HOME}/hermes-agent}"
if [[ ! -d "${CODE_DIR}/hermes_cli" ]]; then
  echo "ERROR: stock code tree not found at ${CODE_DIR} (set HERMES_CODE)" >&2
  exit 1
fi
echo "verifying plugin load (HERMES_HOME=${PROFILE_HOME}, CODE=${CODE_DIR})..."
HERMES_HOME="${PROFILE_HOME}" "${PY}" - <<PYEOF
import sys
sys.path.insert(0, "${CODE_DIR}")
from plugins.memory import load_memory_provider
p = load_memory_provider("mea_pm")
if p is None:
    sys.exit("mea_pm failed to load")
print(f"  loaded: {type(p).__name__} (name={p.name})")
PYEOF

echo "mea_pm install complete."
