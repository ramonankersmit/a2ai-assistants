#!/usr/bin/env bash
set -euo pipefail
DIR="$(dirname "$0")"
bash "$DIR/run_a2a_toeslagen.sh" & 
bash "$DIR/run_a2a_bezwaar.sh" & 
wait
