# AGENTS.md

## Repository overview
This repo contains a standalone demo stack for “Belastingdienst Assistants” (A2UI + MCP + A2A):
- `apps/web-shell`: Vite + Lit UI shell for A2UI surfaces.
- `apps/orchestrator`: FastAPI orchestrator that coordinates MCP tools and A2A agents (SSE `/events`, POST `/api/client-event`).
- `services/mcp_tools`: FastAPI tool server exposing deterministic MCP tools over SSE (`/sse`, POST `/message`).
- `services/a2a_toeslagen_agent`: A2A agent for toeslagen flows (`explain_toeslagen`).
- `services/a2a_bezwaar_agent`: A2A agent for bezwaar flows (`structure_bezwaar`, Gemini optional with fallback).
- `services/a2a_genui_agent`: A2A agent for Generative UI (`compose_ui`, Gemini optional with deterministic fallback).

See `README.md` for protocol details and `docs/README_DEMO.md` for a click-by-click demo runbook.

## A2UI surfaces
Current surfaces in the web shell:
- `home` — tile launcher
- `toeslagen` — deterministic MCP + A2A enrichment
- `bezwaar` — MCP extraction/classification + A2A structured response (Gemini optional)
- `genui_search` — MCP `bd_search` + A2A `compose_ui` that returns UI blocks
- `genui_tree` — MCP `bd_search` + A2A `next_node` that returns decision blocks (wizard)

The UI model includes status paths used across surfaces:
- `/status/loading`, `/status/message`, `/status/step`, `/status/lastRefresh`
- `/status/source`, `/status/sourceReason` (GenUI: `Gemini`/`Fallback` + reason code)
- `/results` (surface output payload)

## Agents & capabilities

### A2A Toeslagen Agent (port 8010)
- **Capability:** `explain_toeslagen`
- **Role:** turns deterministic MCP results into B1 explanations + priority hints.

### A2A Bezwaar Agent (port 8020)
- **Capability:** `structure_bezwaar`
- **Role:** produces a structured case overview, key points, actions, and a concept response.
- **Gemini:** optional (uses `GEMINI_API_KEY`); otherwise deterministic fallback.
- **UI indicator:** concept response includes `[Bron: Gemini]` or `[Bron: Fallback]`.

### A2A GenUI Agent (port 8030)
- **Capabilities:** `compose_ui`, `next_node`
- **Input (compose_ui):** `{ query, citations }`
- **Input (next_node):** `{ state, choice, citations }`
- **Output (normalized by orchestrator):**
  - `blocks`: list of UI blocks (allowed kinds in UI: `callout`, `citations`, `accordion`, `next_questions`, `notice`, `decision`)
  - `ui_source`: `gemini` or `fallback`
  - `ui_source_reason`: reason code (e.g. `resource_exhausted`, `http_429`, `bad_json`)
- **UI indicator:** pill `GenUI: Gemini/Fallback · ...` with a human-friendly reason label.
- **Decision blocks (wizard):** `decision` with `{ question, options[] }` and clickable options.


## Working guidelines
- Prefer small, focused changes per component:
  - UI: `apps/web-shell`
  - orchestration: `apps/orchestrator`
  - MCP tools: `services/mcp_tools`
  - A2A agents: `services/a2a_*`
- Keep environment-specific files out of git (see `.gitignore`).
- If you add or change scripts, update `docs/README_DEMO.md`.
- Prefer deterministic, testable behavior over ad-hoc logic.

## Quick navigation
- UI surfaces and A2UI rendering: `apps/web-shell/src/`
- Orchestration logic + SSE: `apps/orchestrator/`
- MCP tools implementations + dataset: `services/mcp_tools/` (data under `services/mcp_tools/data/`)
- A2A agents: `services/a2a_toeslagen_agent/`, `services/a2a_bezwaar_agent/`, `services/a2a_genui_agent/`
