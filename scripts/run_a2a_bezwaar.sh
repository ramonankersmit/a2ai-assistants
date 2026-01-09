#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../services/a2a_bezwaar_agent"
python -m uvicorn server:app --host 127.0.0.1 --port 8020
