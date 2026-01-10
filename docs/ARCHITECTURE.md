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

## Sequence — Toeslagen Check (progressive updates)

```mermaid
sequenceDiagram
  participant W as Web Shell
  participant O as Orchestrator
  participant MCP as MCP Toolserver
  participant A2AT as A2A Toeslagen Agent

  W->>O: POST client-event toeslagen/check
  O-->>W: A2UI dataModelUpdate (A2UI: Voorwaarden ophalen…)
  O->>MCP: tools/call rules_lookup
  MCP-->>O: result rules
  O-->>W: dataModelUpdate (MCP: rules_lookup (Nms)) + results

  O-->>W: dataModelUpdate (A2UI: Checklist samenstellen…)
  O->>MCP: tools/call doc_checklist
  MCP-->>O: result checklist
  O-->>W: dataModelUpdate (MCP: doc_checklist (Nms)) + results

  O-->>W: dataModelUpdate (A2UI: Aandachtspunten berekenen…)
  O->>MCP: tools/call risk_notes
  MCP-->>O: result risks
  O-->>W: dataModelUpdate (MCP: risk_notes (Nms)) + results

  O-->>W: dataModelUpdate (A2UI: Uitleg in B1 (agent)…)
  O->>A2AT: message/send explain_toeslagen
  A2AT-->>O: enriched items
  O-->>W: dataModelUpdate (A2A: explain_toeslagen (Nms)) + results

  O-->>W: dataModelUpdate (A2UI: Klaar…)
```

## Sequence — Bezwaar Assistent (Gemini optioneel)

```mermaid
sequenceDiagram
  participant W as Web Shell
  participant O as Orchestrator
  participant MCP as MCP Toolserver
  participant A2AB as A2A Bezwaar Agent
  participant G as Gemini

  W->>O: POST client-event bezwaar/analyse
  O-->>W: dataModelUpdate (A2UI: Entiteiten extraheren…)
  O->>MCP: tools/call extract_entities
  MCP-->>O: entities
  O-->>W: dataModelUpdate + partial results

  O-->>W: dataModelUpdate (A2UI: Zaak classificeren…)
  O->>MCP: tools/call classify_case
  MCP-->>O: classification
  O->>MCP: tools/call policy_snippets
  MCP-->>O: snippets
  O-->>W: dataModelUpdate (MCP: ...) + results

  O-->>W: dataModelUpdate (A2UI: Juridische structuur (agent)…)
  O->>A2AB: message/send structure_bezwaar

  alt GEMINI_API_KEY aanwezig
    A2AB->>G: generate draft_response
    G-->>A2AB: draft text
  else fallback
    A2AB-->>A2AB: deterministic placeholder
  end

  A2AB-->>O: structured output
  O-->>W: dataModelUpdate (A2A: structure_bezwaar (Nms)) + results
  O-->>W: dataModelUpdate (A2UI: Klaar…)
```
