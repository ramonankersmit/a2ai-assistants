# AGENTS.md — Overheid Assistants (MVP)

## Componenten (processen)

### 1) Web Shell (Vite + Lit)
- URL: `http://127.0.0.1:5173`
- Functie: rendert A2UI surfaces (`home`, `toeslagen`, `bezwaar`) en past `dataModelUpdate` patches toe.
- Transport:
  - SSE van orchestrator: `GET http://localhost:10002/events`
  - ClientEvents naar orchestrator: `POST http://localhost:10002/api/client-event`

### 2) Orchestrator (FastAPI)
- URL: `http://localhost:10002`
- Functie: orchestration + progressive updates:
  - roept MCP tools aan (deterministisch, fake latency 300–700ms)
  - roept A2A agents aan (één per flow)
  - stuurt na elke stap een aparte A2UI update + wacht 0.6s

### 3) MCP Toolserver (FastAPI, SSE transport)
- URL: `http://127.0.0.1:8000`
- SSE handshake: `GET /sse` (orchestrator gebruikt `MCP_SSE_URL`)
- Message endpoint: `POST /message` (JSON-RPC, gekoppeld via `X-SSE-ID`)
- Tools (demo):
  - `rules_lookup(regeling, jaar)`
  - `doc_checklist(regeling, situatie)`
  - `risk_notes(inputs...)`
  - `extract_entities(text)`
  - `classify_case(text)`
  - `policy_snippets(type)`

### 4) A2A Toeslagen Agent (FastAPI, JSON-RPC)
- URL: `http://localhost:8010/`
- Agent card: `GET /.well-known/agent-card.json`
- JSON-RPC endpoint: `POST /`
- Capability:
  - `explain_toeslagen`
- Output: verrijkte items met:
  - `b1_explanation` (1–2 zinnen)
  - `priority` (hoog/midden/laag)

### 5) A2A Bezwaar Agent (FastAPI, JSON-RPC)
- URL: `http://localhost:8020/`
- Agent card: `GET /.well-known/agent-card.json`
- JSON-RPC endpoint: `POST /`
- Capability:
  - `structure_bezwaar`
- Output JSON:
  - `overview` (type, reden, datum, onderwerp, timeline, snippets)
  - `key_points[]`
  - `actions[]`
  - `draft_response` (Gemini indien `GEMINI_API_KEY`, anders fallback)

## A2UI protocol (in deze MVP)

### Surface IDs
- `home`
- `toeslagen`
- `bezwaar`

### Berichten (SSE `data:` JSON)
1) **surface/open**
```json
{
  "kind": "surface/open",
  "surfaceId": "toeslagen",
  "title": "Toeslagen Check",
  "dataModel": { "...": "..." }
}
```

2) **dataModelUpdate**
```json
{
  "kind": "dataModelUpdate",
  "surfaceId": "toeslagen",
  "patches": [
    { "op": "replace", "path": "/status/loading", "value": true },
    { "op": "replace", "path": "/status/message", "value": "..." }
  ]
}
```

### Data model schema (vereist)
- `/status/loading` (bool)
- `/status/message` (string)
- `/status/step` (string)
- `/status/lastRefresh` (string)
- `/results` (list of objects)

De UI rendert expliciet:
- status panel: `/status/loading`, `/status/message`, `/status/step`, `/status/lastRefresh`
- resultaten: `/results`

## A2A protocol (vereist)

Orchestrator roept A2A agent aan met JSON-RPC:
- `jsonrpc: "2.0"`
- `method: "message/send"`
- `params.message.kind = "message"`
- `params.message.messageId = uuid`
- `params.message.role = "user"`
- `params.message.parts[0].kind = "data"`
- `parts[0].metadata.mimeType = "application/json"`

## MCP protocol (vereist)

- Orchestrator maakt per tool-call een SSE connectie naar `MCP_SSE_URL` (default `http://127.0.0.1:8000/sse`)
- Server stuurt event `endpoint` met:
  - `sse_id`
  - `post_url` (hier: `/message`)
- Orchestrator POST JSON-RPC naar `post_url` met header `X-SSE-ID: <sse_id>`
- Server antwoordt via SSE event `message` met JSON-RPC response (zelfde `id`)

## Demo talk track (± 5 minuten)

1. **Start**: “Dit is een minimalistische Overheid-achtige shell met twee assistenten.”
2. **A2UI**: “De UI krijgt surfaces en dataModelUpdate patches via SSE; we tonen bewust progressive updates.”
3. **Flow Toeslagen**:
   - “Orchestrator calls MCP tools deterministisch (rules/checklist/risks) met fake latency.”
   - “Daarna verrijkt een A2A agent de inhoud met B1-uitleg en prioriteit.”
4. **Flow Bezwaar**:
   - “Eerst MCP: entiteiten + classificatie + policy snippets.”
   - “Dan A2A: structuur (overzicht, punten, acties) en conceptreactie (Gemini of fallback).”
5. **Waarom dit pattern**:
   - “Deterministische tools voor controleerbare stappen; agent(s) voor taal/structuur; A2UI voor consistente UI-updates.”
