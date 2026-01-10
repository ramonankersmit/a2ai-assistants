# Architectuur — Belastingdienst Assistants (MVP)

Deze MVP bestaat uit een web-shell (A2UI renderer), een orchestrator (A2UI SSE + flowlogica), een MCP toolserver (SSE transport) en twee A2A agents (JSON-RPC). De Bezwaar-agent kan optioneel Gemini gebruiken.

## Componentdiagram (Mermaid)

```mermaid
flowchart LR
  U["Gebruiker"] -->|"Browser"| W["Web Shell (Vite + Lit) · A2UI renderer"]

  W <-->|"SSE /events (A2UI messages)"| O["Orchestrator (FastAPI) · A2UI hub + flows"]
  W -->|"POST /api/client-event (ClientEvents)"| O

  O <-->|"SSE GET /sse (JSON-RPC responses)"| MCP["MCP Toolserver (FastAPI) · deterministische tools"]
  O -->|"POST /message (JSON-RPC tools/call)"| MCP

  O -->|"JSON-RPC message/send"| A2AT["A2A Toeslagen Agent"]
  O -->|"JSON-RPC message/send"| A2AB["A2A Bezwaar Agent"]

  A2AB -->|"optioneel"| G["Gemini API (GEMINI_API_KEY)"]
```