#!/usr/bin/env bash
# mea_sessions install — tracked, idempotent. Installs the vendored engine's
# runtime deps into the stock Hermes runtime interpreter and verifies the
# plugin loads, the `sessions` tool registers, and the legacy `session_search`
# is deregistered.
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

# ── 4. Verify the plugin loads, the tool registers, legacy is deregistered ──
# The plugin lives at <profile_home>/plugins/mea_sessions, so the profile home is
# two levels up. Point HERMES_HOME at THIS profile — not the base home.
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
from hermes_cli.plugins import discover_plugins
from tools.registry import registry
discover_plugins(force=True)
entry = registry.get_entry("sessions")
if entry is None:
    sys.exit("sessions tool did not register")
print(f"  registered: sessions (toolset={entry.toolset}, emoji={entry.emoji!r})")
legacy = registry.get_entry("session_search")
if legacy is not None:
    sys.exit("legacy session_search still registered (deregister failed)")
print("  legacy session_search: deregistered OK")
PYEOF

# ── 5. Apply the session-scope migration and repair existing rows ────────────
# PG columns chat_id/thread_id/chat_topic/display_name exist in the mirror's
# schema but nothing ever wrote them: the upsert listed 9 columns only, so all
# session rows carried NULL scope and recall could not filter by topic/thread.
# The numbered migration (jpm/core/_migrations/0076_session_topic_scope.sql) is
# applied by apply_schema on plugin load; the backfill then repairs rows already
# in PG from state.db, which is the only place those values ever lived.
echo "applying session-scope migration + backfill..."
HERMES_HOME="${PROFILE_HOME}" "${PY}" - <<PYEOF
import sys
sys.path.insert(0, "${PROFILE_HOME}/plugins/mea_pm")
sys.path.insert(0, "${PROFILE_HOME}/plugins/mea_sessions")
from jpm.core._pg import apply_schema
apply_schema()
print("  schema/migrations: applied")
from _backfill_topic_scope import backfill
print(f"  backfill: {backfill()}")
PYEOF

echo "mea_sessions install complete."
