#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../services/mcp_tools"
python -m uvicorn server:app --host 127.0.0.1 --port 8000
