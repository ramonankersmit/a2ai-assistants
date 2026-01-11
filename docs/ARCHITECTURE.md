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

---

# Aanvullingen — GenUI (Zoeken / Wizard / Formulier)

Onderstaande diagrammen voegen de nieuwe GenUI-stromen toe. De bestaande diagrammen hierboven blijven ongewijzigd.

## Component-aanvulling — GenUI (Mermaid)

```mermaid
flowchart LR
  W["Web Shell (Vite + Lit)\nA2UI renderer"] <-->|"SSE /events"| O["Orchestrator (FastAPI)\nA2UI hub + flows"]

  O -->|"JSON-RPC message/send"| A2AG["A2A GenUI Agent\n(capabilities: compose_ui, next_node, compose_form, extend_form, explain_form)"]

  O -->|"POST /message (tools/call)"| MCP["MCP Toolserver\n(bd_search + validate_form)"]
  MCP --- DATA["Curated dataset\nbd_pages.json"]

  A2AG -->|"optioneel"| G["Gemini API\n(GEMINI_API_KEY)"]
```

## Sequence — GenUI Zoeken (progressive updates)

```mermaid
sequenceDiagram
  participant W as Web Shell
  participant O as Orchestrator
  participant MCP as MCP Toolserver
  participant A2AG as A2A GenUI Agent

  W->>O: POST client-event genui/search
  O-->>W: dataModelUpdate (A2UI: Bronnen ophalen (MCP)…)
  O->>MCP: tools/call bd_search
  MCP-->>O: citations
  O-->>W: dataModelUpdate (MCP: bd_search (Nms)) + results(citations)

  O-->>W: dataModelUpdate (A2UI: UI-blokken samenstellen (A2A)…)
  O->>A2AG: message/send compose_ui
  A2AG-->>O: blocks (callout/accordion/next_questions/…)
  O-->>W: dataModelUpdate (A2A: compose_ui (Nms)) + results(blocks)

  O-->>W: dataModelUpdate (A2UI: Klaar…)
```

## Sequence — GenUI Wizard (decision tree)

```mermaid
sequenceDiagram
  participant W as Web Shell
  participant O as Orchestrator
  participant A2AG as A2A GenUI Agent

  Note over W,O: Bij openen van genui_tree start de orchestrator automatisch de wizard

  W->>O: surface/open genui_tree
  O-->>W: dataModelUpdate (A2UI: Wizard starten…)

  O->>A2AG: message/send next_node
  A2AG-->>O: decision block
  O-->>W: dataModelUpdate + results(decision)

  W->>O: POST client-event genui_tree/choose
  O-->>W: dataModelUpdate (A2UI: Volgende stap…)
  O->>A2AG: message/send next_node (path + state)
  A2AG-->>O: decision of result blocks
  O-->>W: dataModelUpdate + results(update)
```

## Sequence — GenUI Formulier (generate / change / submit)

```mermaid
sequenceDiagram
  participant W as Web Shell
  participant O as Orchestrator
  participant MCP as MCP Toolserver
  participant A2AG as A2A GenUI Agent

  W->>O: POST client-event genui_form/generate
  O-->>W: dataModelUpdate (A2UI: Bronnen ophalen (MCP)…)
  O->>MCP: tools/call bd_search
  MCP-->>O: citations
  O-->>W: dataModelUpdate + results(citations)

  O-->>W: dataModelUpdate (A2UI: Formulier opstellen (A2A)…)
  O->>A2AG: message/send compose_form
  A2AG-->>O: blocks (incl. form)
  Note over O: Fail-safe: orchestrator garandeert altijd een form-block met fields
  O-->>W: dataModelUpdate + results(form + overige blocks)

  W->>O: POST client-event genui_form/change (debounced)
  O-->>W: dataModelUpdate (A2UI: Formulier aanvullen (A2A)…)
  O->>A2AG: message/send extend_form
  A2AG-->>O: extra_fields (optioneel)
  Note over O: Variant B (agent-first) met fallback op Variant A (deterministisch)
  O-->>W: dataModelUpdate + results(form updated)

  W->>O: POST client-event genui_form/submit
  O-->>W: dataModelUpdate (A2UI: Formulier controleren…)
  O->>MCP: tools/call validate_form
  MCP-->>O: ok / errors
  O->>A2AG: message/send explain_form
  A2AG-->>O: notice + vervolgstappen (callout/next_questions)
  O-->>W: dataModelUpdate + results(explain blocks)
```

## Sequence — Toeslagen Reset

```mermaid
sequenceDiagram
  participant W as Web Shell
  participant O as Orchestrator

  W->>O: POST client-event toeslagen/reset
  O-->>W: surface/open toeslagen (empty model)
  O-->>W: dataModelUpdate (A2UI: Vul de gegevens in en klik op Check.)
```

## Notities — stabiliteit en fallback

- **Event-aliases:** de orchestrator accepteert (waar relevant) zowel `genui/form_*` als `genui_form/*` varianten om UI/flow-compatibiliteit te behouden.
- **Whitelisting/sanitizing:** de orchestrator laat alleen toegestane block-kinds door (o.a. `form`, `decision`, `callout`, `notice`, `next_questions`, `citations`).
- **Fail-safe formulier:** ook als `compose_form` geen (bruikbaar) form-block oplevert, injecteert de orchestrator een deterministisch form-block zodat de demo altijd invulvelden toont.
- **Variant B + pruning:** toegevoegde velden kunnen ook weer verdwijnen wanneer triggers wegvallen (bijv. bedrag leeg/0, kenmerk te kort).
