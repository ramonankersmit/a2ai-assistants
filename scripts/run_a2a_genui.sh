#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../services/a2a_genui_agent"

if [[ ! -f "server.py" ]]; then
  echo "ERROR: services/a2a_genui_agent/server.py ontbreekt."
  echo "Zorg dat de GenUI agent file exact 'server.py' heet."
  ls -la
  exit 1
fi

python -m uvicorn server:app --host 127.0.0.1 --port 8030
