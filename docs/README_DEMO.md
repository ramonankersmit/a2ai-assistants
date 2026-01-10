# Belastingdienst Assistants (MVP) — README_DEMO

Standalone demo-repo met:
- Web shell (Vite + Lit) met A2UI surfaces + `dataModelUpdate`
- Orchestrator (FastAPI) met progressive updates (0.6s) en status-prefixes: **A2UI / MCP / A2A**
- MCP toolserver (FastAPI) met **SSE transport** (`/sse` + `POST /message`)
- 2x A2A agent servers (FastAPI) met agent-card + JSON-RPC (`message/send`)
- Bezwaar-agent: **Gemini optioneel** (zichtbaar via `[Bron: Gemini]` / `[Bron: Fallback]`)

---

## 1) Prereqs (Windows)

- Python 3.10+ (aanrader: 3.11)
- Node.js 18+ (npm)
- Git Bash of CMD/PowerShell

---

## 2) Install (1x)

Open een terminal in repo-root.

### 2.1 Config (.env)
**Git Bash**
```bash
cp .env.example .env
```

**CMD/PowerShell**
```bat
copy .env.example .env
```

Optioneel: vul `GEMINI_API_KEY` in `.env`. Zonder key wordt deterministic fallback gebruikt.

### 2.2 Python venv + deps
**Git Bash**
```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**CMD/PowerShell**
```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2.3 Web deps
```bash
cd apps/web-shell
npm install
cd ../..
```

---

## 3) Starten (alle processen)

### Optie A — scripts (aanrader)

**Git Bash (aanrader als je Git Bash gebruikt)**
```bash
bash scripts/run_all.sh
```

**CMD/PowerShell**
```bat
scripts\run_all.cmd
```

Poorten:
- MCP tools: `http://127.0.0.1:8000`
- A2A toeslagen: `http://127.0.0.1:8010`
- A2A bezwaar: `http://127.0.0.1:8020`
- Orchestrator: `http://127.0.0.1:10002`
- Web: `http://127.0.0.1:5173`

### Optie B — handmatig (per terminal)

Let op: start deze commando’s **vanaf repo-root** (belangrijk i.v.m. package-imports).

**Terminal 1 (MCP)**
```bat
.venv\Scripts\activate
python -m uvicorn services.mcp_tools.server:app --host 127.0.0.1 --port 8000
```

**Terminal 2 (A2A toeslagen)**
```bat
.venv\Scripts\activate
python -m uvicorn services.a2a_toeslagen_agent.server:app --host 127.0.0.1 --port 8010
```

**Terminal 3 (A2A bezwaar)**
```bat
.venv\Scripts\activate
python -m uvicorn services.a2a_bezwaar_agent.server:app --host 127.0.0.1 --port 8020
```

**Terminal 4 (Orchestrator)**
```bat
.venv\Scripts\activate
python -m uvicorn apps.orchestrator.main:app --host 127.0.0.1 --port 10002
```

**Terminal 5 (Web)**
```bat
cd apps\web-shell
npm run dev
```

---

## 4) Demo runbook (clicks)

1. Open `http://127.0.0.1:5173`
2. Startscherm toont tegels (Toeslagen Check / Bezwaar Assistent)
3. Elke run reset de surface (A2UI `surface/open`) zodat herhaalde runs weer duidelijk zichtbaar zijn.

### UI gedrag (wat je laat zien)
- Statusregels in de log beginnen met:
  - `A2UI:` (UI/flow-stappen)
  - `MCP:` (tool-call + latency, bv. `MCP: rules_lookup (412ms)`)
  - `A2A:` (agent-call + latency)
- Statuspaneel is inklapbaar.
- “Progressive updates” zijn expres niet gebatcht: na elke update ~0.6s delay.

### Demo Flow 1 — Toeslagen Check
1. Klik **Start** op *Toeslagen Check*
2. Kies inputs en klik **Check**
3. Je ziet minimaal 4 progressive updates (status verandert + inhoud groeit):
   - `A2UI: Voorwaarden ophalen…`
   - `MCP: rules_lookup (Nms)` + voorwaarden/resultaten
   - `A2UI: Checklist samenstellen…`
   - `MCP: doc_checklist (Nms)` + eerste documenten
   - `A2UI: Aandachtspunten berekenen…`
   - `MCP: risk_notes (Nms)` + aandachtspunten
   - `A2UI: Uitleg in B1 (agent)…`
   - `A2A: explain_toeslagen (Nms)` + verrijking (prioriteit-icoontjes)

### Demo Flow 2 — Bezwaar Assistent
1. Klik **Start** op *Bezwaar Assistent*
2. Plak (of laat staan) demo-tekst en klik **Analyseer**
3. Je ziet minimaal 4 progressive updates:
   - `A2UI: Entiteiten extraheren…`
   - `MCP: extract_entities (Nms)` → zaakveldjes vullen
   - `A2UI: Zaak classificeren…`
   - `MCP: classify_case (Nms)` en `MCP: policy_snippets (Nms)` → type/reden/snippets
   - `A2UI: Juridische structuur (agent)…`
   - `A2A: structure_bezwaar (Nms)` → key points + acties + concept
4. In “Concept Reactie” zie je expliciet:
   - `[Bron: Gemini]` of `[Bron: Fallback]`

---

## 5) Troubleshooting (Windows)

- **CORS errors**: gebruik exact de poorten uit dit document.
- **Web laadt niet**: check of `npm install` in `apps/web-shell` is uitgevoerd.
- **Orchestrator kan tools niet callen**: check of MCP draait en `MCP_SSE_URL` in `.env` wijst naar `http://127.0.0.1:8000/sse`.
- **MCP /message 405 in browser**: dat is normaal; `/message` accepteert alleen **POST**.
- **A2A call faalt**: check of agents draaien op `8010` en `8020`.
- **Gemini faalt**: demo valt automatisch terug op fallback (zichtbaar in de UI).

---

## 6) Belangrijke demo-notes

- Geen echte persoonsgegevens; alle content is demo/placeholder.
- Output is **geen besluit**, alleen demo-UI en demo-orchestratie.
- Progressive updates worden expres **niet gebatcht** (0.6s delay per stap).
