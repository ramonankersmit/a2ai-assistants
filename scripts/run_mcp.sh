#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m uvicorn services.mcp_tools.server:app --host 127.0.0.1 --port 8000
