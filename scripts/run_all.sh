#!/usr/bin/env bash
set -euo pipefail
DIR="$(dirname "$0")"
bash "$DIR/run_mcp.sh" &
bash "$DIR/run_a2a.sh" &
bash "$DIR/run_orchestrator.sh" &
bash "$DIR/run_web.sh" &
wait
