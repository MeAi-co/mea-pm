#!/usr/bin/env bash
# Runner for recall_baseline.py — loads the arm's .env (PG creds, OLLAMA) then
# drives the REAL recall_context entry point as the arm user.
# Usage: run_baseline.sh <label>
set -euo pipefail
LABEL="${1:-run}"
HERE="$(cd "$(dirname "$0")" && pwd)"
HOME_DIR="/home/bench_a/.hermes"
# Resolve the interpreter from the arm's LIVE install venv — that is where
# psycopg2 lives (the bare tool python has no psycopg2). Never hardcode the
# version dir: its name contains a substring the redaction layer masks.
VENV="$(ls -d /home/bench_a/.hermes/installs/*/environments/*/venv 2>/dev/null | head -1)"
PY="$VENV/bin/python3"
[ -x "$PY" ] || { echo "FATAL: no arm venv python found under /home/bench_a/.hermes/installs/*/environments/*/venv" >&2; exit 1; }

# Load .env (export every KEY=VALUE, ignore comments/blanks).
set -a
# shellcheck disable=SC1091
source "$HOME_DIR/.env"
set +a
export HERMES_HOME="$HOME_DIR"

OUT="/tmp/recall_${LABEL}.json"
"$PY" "$HERE/recall_baseline.py" --label "$LABEL" --out "$OUT"
echo "OUT=$OUT"
