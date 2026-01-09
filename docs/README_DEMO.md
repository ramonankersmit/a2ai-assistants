# Belastingdienst Assistants (MVP)

Standalone demo-repo met:
- Web shell (Vite + Lit) met A2UI surfaces + dataModelUpdate
- Orchestrator (FastAPI) met progressive updates (0.6s)
- MCP toolserver (FastAPI) met **SSE transport**
- 2x A2A agent servers (FastAPI) met agent-card + JSON-RPC (`message/send`)

## 1) Prereqs (Windows)

- Python 3.10+ (aanrader: 3.11)
- Node.js 18+ (npm)
- Git Bash of CMD/PowerShell

## 2) Install (1x)

Open een terminal in repo-root:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Optioneel: vul `GEMINI_API_KEY` in `.env`. Zonder key wordt deterministic fallback gebruikt.

## 3) Starten (4 processen)

### Optie A — met scripts (aanrader)
Open repo-root en run:

```bat
scripts\run_all.cmd
```

Dit opent 4 terminals:
- MCP tools: `http://127.0.0.1:8000`
- A2A toeslagen: `http://localhost:8010`
- A2A bezwaar: `http://localhost:8020`
- Orchestrator: `http://localhost:10002`
- Web: `http://127.0.0.1:5173`

### Optie B — handmatig (per terminal)

**Terminal 1 (MCP)**
```bat
.venv\Scripts\activate
cd services\mcp_tools
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

**Terminal 2 (A2A toeslagen)**
```bat
.venv\Scripts\activate
cd services\a2a_toeslagen_agent
python -m uvicorn server:app --host 127.0.0.1 --port 8010
```

**Terminal 3 (A2A bezwaar)**
```bat
.venv\Scripts\activate
cd services\a2a_bezwaar_agent
python -m uvicorn server:app --host 127.0.0.1 --port 8020
```

**Terminal 4 (Orchestrator)**
```bat
.venv\Scripts\activate
cd apps\orchestrator
python -m uvicorn main:app --host 127.0.0.1 --port 10002
```

**Terminal 5 (Web)**
```bat
cd apps\web-shell
npm install
npm run dev -- --port 5173
```

## 4) Demo runbook (clicks)

1. Open `http://127.0.0.1:5173`
2. Startscherm toont 2 tegels (Toeslagen Check / Bezwaar Assistent)

### Demo Flow 1 — Toeslagen Check
1. Klik **Start** op *Toeslagen Check*
2. Kies inputs en klik **Check**
3. Je ziet minimaal 4 progressive updates (status verandert + inhoud groeit):
   - Voorwaarden ophalen (MCP)
   - Checklist samenstellen (MCP) → eerste items zichtbaar
   - Aandachtspunten berekenen (MCP) → extra inhoud
   - Uitleg in B1 (A2A) → verrijkte items met priority + B1 uitleg

### Demo Flow 2 — Bezwaar Assistent
1. Klik **Start** op *Bezwaar Assistent*
2. Plak (of laat staan) demo-tekst en klik **Analyseer**
3. Je ziet minimaal 4 progressive updates:
   - Entiteiten extraheren (MCP) → zaakveldjes vullen
   - Zaak classificeren (MCP) → type/reden
   - Juridische structuur (A2A) → key points + acties
   - Concept reactie (Gemini of fallback) → conceptreactie

## 5) Troubleshooting (Windows)

- **CORS errors**: gebruik exact de poorten uit README. Orchestrator, MCP en agents hebben CORS open voor `localhost` en `127.0.0.1`.
- **Web laadt niet**: check of `npm install` in `apps/web-shell` is uitgevoerd.
- **Orchestrator kan tools niet callen**: check of MCP op `http://127.0.0.1:8000/sse` draait (zie `.env`).
- **A2A call faalt**: check of agents draaien op `8010` en `8020`.
- **Gemini faalt**: demo valt automatisch terug op deterministic conceptreactie.

## 6) Belangrijke demo-notes

- Geen echte persoonsgegevens; alle content is demo/placeholder.
- Output is **geen besluit**, alleen demo-UI en demo-orchestratie.
- Progressive updates worden expres **niet gebatcht** (0.6s delay per stap).
