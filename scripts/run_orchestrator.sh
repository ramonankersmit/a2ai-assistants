#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../apps/orchestrator"
python -m uvicorn main:app --host 127.0.0.1 --port 10002
