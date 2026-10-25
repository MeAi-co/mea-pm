#!/usr/bin/env bash
# Runner for recall_baseline.py — loads the runtime .env (PG creds, OLLAMA) then
# drives the REAL recall_context entry point.
#
# Usage: run_baseline.sh <label>
#
# Env:
#   JOSHAICO_HOME   runtime home holding .env and config.yaml (required)
#   PYTHON          interpreter to use (default: python3 on PATH)
set -euo pipefail
LABEL="${1:-run}"
HERE="$(cd "$(dirname "$0")" && pwd)"

: "${JOSHAICO_HOME:?set JOSHAICO_HOME to the runtime home (holds .env + config.yaml)}"
PY="${PYTHON:-python3}"

command -v "$PY" >/dev/null 2>&1 || { echo "FATAL: interpreter '$PY' not found" >&2; exit 1; }

# Load .env (export every KEY=VALUE, ignore comments/blanks).
if [ -f "$JOSHAICO_HOME/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$JOSHAICO_HOME/.env"
  set +a
fi

OUT="${OUT:-/tmp/recall_${LABEL}.json}"
"$PY" "$HERE/recall_baseline.py" --label "$LABEL" --out "$OUT"
echo "OUT=$OUT"
