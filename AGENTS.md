# AGENTS.md

## Repository overview
This repo contains a demo stack for Belastingdienst-themed assistants:
- `apps/web-shell`: Vite + Lit UI shell for A2UI surfaces.
- `apps/orchestrator`: FastAPI orchestrator that coordinates MCP tools and A2A agents.
- `services/mcp_tools`: FastAPI tool server exposing MCP tools.
- `services/a2a_toeslagen_agent`: A2A agent for toeslagen flows.
- `services/a2a_bezwaar_agent`: A2A agent for bezwaar flows.

See `README.md` for protocol details and demo flow notes.

## Working guidelines
- Prefer small, focused changes per component (UI in `apps/web-shell`, orchestration in `apps/orchestrator`, agents/tools in `services/*`).
- Keep environment-specific files out of git (see `.gitignore`).
- If you add new commands or scripts, document them in `README.md` or under `docs/`.
- When relevant, add or update tests and run the full test suite before submitting changes.

## Best practices
- Follow existing project structure and naming conventions.
- Keep changes scoped and avoid unrelated refactors in the same change set.
- Update or add documentation when behavior or usage changes.
- Prefer deterministic, testable behavior over ad-hoc logic.

## Quick navigation
- UI surfaces and A2UI rendering: `apps/web-shell/src/`
- Orchestration logic + SSE: `apps/orchestrator/`
- MCP tools implementations: `services/mcp_tools/`
- A2A agents: `services/a2a_toeslagen_agent/`, `services/a2a_bezwaar_agent/`
