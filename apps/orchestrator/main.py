from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from a2ui import SessionHub, now_iso, surface_open
from a2a_client import A2AClient
from mcp_client import MCPClient

Json = Dict[str, Any]

load_dotenv()

ORCH_PORT = int(os.getenv("ORCH_PORT", "10002"))
MCP_SSE_URL = os.getenv("MCP_SSE_URL", "http://127.0.0.1:8000/sse")
A2A_TOESLAGEN_URL = os.getenv("A2A_TOESLAGEN_URL", "http://localhost:8010/")
A2A_BEZWAAR_URL = os.getenv("A2A_BEZWAAR_URL", "http://localhost:8020/")

hub = SessionHub()
mcp = MCPClient(MCP_SSE_URL)
a2a_toes = A2AClient(A2A_TOESLAGEN_URL)
a2a_bez = A2AClient(A2A_BEZWAAR_URL)

app = FastAPI(title="Belastingdienst Assistants Orchestrator", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:10002",
        "http://127.0.0.1:10002",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _home_surface_model() -> Json:
    return {
        "status": {
            "loading": False,
            "message": "Kies een assistent om te starten.",
            "step": "idle",
            "lastRefresh": now_iso(),
        },
        "results": [],
    }


def _empty_surface_model(message: str) -> Json:
    return {
        "status": {
            "loading": False,
            "message": message,
            "step": "idle",
            "lastRefresh": now_iso(),
        },
        "results": [],
    }


async def _send_open_surface(sid: str, surface_id: str, title: str, initial_model: Json) -> None:
    s = await hub.get(sid)
    if not s:
        return
    s.models[surface_id] = initial_model
    await hub.push(sid, surface_open(surface_id, title, initial_model))


async def _set_status(
    sid: str,
    surface_id: str,
    *,
    loading: Optional[bool] = None,
    message: Optional[str] = None,
    step: Optional[str] = None,
) -> None:
    patches: List[Json] = []
    if loading is not None:
        patches.append({"op": "replace", "path": "/status/loading", "value": loading})
    if message is not None:
        patches.append({"op": "replace", "path": "/status/message", "value": message})
    if step is not None:
        patches.append({"op": "replace", "path": "/status/step", "value": step})
    patches.append({"op": "replace", "path": "/status/lastRefresh", "value": now_iso()})
    await hub.push_update_and_apply(sid, surface_id, patches)


async def _set_results(sid: str, surface_id: str, results: List[Json]) -> None:
    await hub.push_update_and_apply(sid, surface_id, [{"op": "replace", "path": "/results", "value": results}])


async def _append_results(sid: str, surface_id: str, extra: List[Json]) -> None:
    s = await hub.get(sid)
    if not s:
        return
    model = s.get_model(surface_id)
    current = model.get("results") or []
    if not isinstance(current, list):
        current = []
    new = current + extra
    await _set_results(sid, surface_id, new)


async def _sleep_tick() -> None:
    # Required: show progressive updates (do not batch)
    await asyncio.sleep(0.6)


def _ms(dt_seconds: float) -> int:
    return int(round(dt_seconds * 1000))


async def _mcp_call_with_trace(
    sid: str,
    surface_id: str,
    tool_name: str,
    args: Json,
    *,
    step: Optional[str] = None,
) -> Json:
    """
    Call an MCP tool and emit a status update including measured latency.

    This intentionally uses /status/message so the web UI's statusHistory can show
    a compact "MCP: tool (Nms)" trace line during the progressive flow.
    """
    t0 = time.perf_counter()
    try:
        result = await mcp.call_tool(tool_name, args)
        dt = _ms(time.perf_counter() - t0)
        await _set_status(sid, surface_id, loading=True, message=f"MCP: {tool_name} ({dt}ms)", step=step or tool_name)
        return result
    except Exception:
        dt = _ms(time.perf_counter() - t0)
        await _set_status(sid, surface_id, loading=True, message=f"MCP: {tool_name} mislukt ({dt}ms)", step=step or tool_name)
        raise


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/events")
async def events(request: Request):
    """A2UI stream (SSE) used by the web shell."""
    session = await hub.create()

    async def gen():
        # session id first
        yield f"data: {JSONResponse(content={'kind':'session/created','sessionId':session.session_id}).body.decode('utf-8')}\n\n"

        # open home surface
        await _send_open_surface(session.session_id, "home", "Belastingdienst Assistants", _home_surface_model())
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(session.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            yield f"data: {JSONResponse(content=msg).body.decode('utf-8')}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/client-event")
async def client_event(payload: Json = Body(...)):
    sid = payload.get("sessionId")
    if not sid:
        raise HTTPException(400, "Missing sessionId")
    s = await hub.get(sid)
    if not s:
        raise HTTPException(404, "Unknown session")

    name = payload.get("name")
    surface_id = payload.get("surfaceId", "home")
    data = payload.get("payload") or {}

    if name == "nav/open":
        target = data.get("surfaceId")
        if target == "toeslagen":
            await _send_open_surface(sid, "toeslagen", "Toeslagen Check", _empty_surface_model("Vul de gegevens in en klik op Check."))
        elif target == "bezwaar":
            await _send_open_surface(sid, "bezwaar", "Bezwaar Assistent", _empty_surface_model("Plak een bezwaarbrief en klik op Analyseer."))
        else:
            await _send_open_surface(sid, "home", "Belastingdienst Assistants", _home_surface_model())
        return {"ok": True}

    if name == "toeslagen/check":
        asyncio.create_task(run_toeslagen_flow(sid, data))
        return {"ok": True}

    if name == "bezwaar/analyse":
        asyncio.create_task(run_bezwaar_flow(sid, data))
        return {"ok": True}

    return {"ok": True, "ignored": True}


async def run_toeslagen_flow(sid: str, inputs: Json) -> None:
    surface_id = "toeslagen"
    await _set_status(sid, surface_id, loading=True, message="Voorwaarden ophalen (MCP)…", step="rules_lookup")
    await _sleep_tick()

    regeling = inputs.get("regeling", "Huurtoeslag")
    jaar = int(inputs.get("jaar", 2024))
    situatie = inputs.get("situatie", "Alleenstaand")
    loon_of_vermogen = bool(inputs.get("loonOfVermogen", True))

    voorwaarden = await _mcp_call_with_trace(sid, surface_id, "rules_lookup", {"regeling": regeling, "jaar": jaar}, step="rules_lookup")
    await _append_results(sid, surface_id, [{"kind": "voorwaarden", "title": "Voorwaarden", "items": voorwaarden.get("voorwaarden", [])}])

    await _set_status(sid, surface_id, loading=True, message="Checklist samenstellen…", step="doc_checklist")
    await _sleep_tick()

    checklist = await _mcp_call_with_trace(sid, surface_id, "doc_checklist", {"regeling": regeling, "situatie": situatie}, step="doc_checklist")
    docs = checklist.get("documenten", [])
    await _append_results(sid, surface_id, [{"kind": "documenten", "title": "Benodigde Documenten", "items": docs[:3]}])

    await _set_status(sid, surface_id, loading=True, message="Aandachtspunten berekenen…", step="risk_notes")
    await _sleep_tick()

    notes = await _mcp_call_with_trace(
        sid,
        surface_id,
        "risk_notes",
        {"regeling": regeling, "jaar": jaar, "situatie": situatie, "loonOfVermogen": loon_of_vermogen},
        step="risk_notes",
    )
    risks = notes.get("aandachtspunten", [])
    await _append_results(sid, surface_id, [{"kind": "aandachtspunten", "title": "Aandachtspunten", "items": risks}])

    await _set_status(sid, surface_id, loading=True, message="Uitleg in B1 (A2A)…", step="a2a_explain")
    await _sleep_tick()

    # Build combined items for enrichment
    combined_items: List[Json] = []
    for item in docs:
        combined_items.append({"category": "document", "text": item})
    for item in risks:
        combined_items.append({"category": "aandachtspunt", "text": item})

    enriched = await a2a_toes.message_send(
        "explain_toeslagen",
        {"inputs": {"regeling": regeling, "jaar": jaar, "situatie": situatie}, "items": combined_items},
    )

    await _append_results(sid, surface_id, [{"kind": "verrijking", "title": "Verrijkte uitleg (B1)", "items": enriched.get("items", [])}])

    await _set_status(sid, surface_id, loading=False, message="Klaar. Dit is een demo-uitkomst (geen besluit).", step="done")


async def run_bezwaar_flow(sid: str, inputs: Json) -> None:
    surface_id = "bezwaar"
    text = (inputs.get("text") or "").strip()
    if not text:
        text = "Ik ben het niet eens met de naheffing van €750. Mijn inkomen is te laag voor deze aanslag. Ik vraag om herziening."

    await _set_status(sid, surface_id, loading=True, message="Entiteiten extraheren (MCP)…", step="extract_entities")
    await _sleep_tick()

    entities = await _mcp_call_with_trace(sid, surface_id, "extract_entities", {"text": text}, step="extract_entities")

    # Show partial fields early
    await _set_results(
        sid,
        surface_id,
        [
            {
                "kind": "bezwaar",
                "overview": {
                    "datum": entities.get("datum"),
                    "onderwerp": entities.get("onderwerp"),
                    "bedrag": entities.get("bedrag"),
                },
                "key_points": [],
                "actions": [],
                "draft_response": "",
            }
        ],
    )

    await _set_status(sid, surface_id, loading=True, message="Zaak classificeren…", step="classify_case")
    await _sleep_tick()

    classification = await _mcp_call_with_trace(sid, surface_id, "classify_case", {"text": text}, step="classify_case")
    snippets = await _mcp_call_with_trace(sid, surface_id, "policy_snippets", {"type": classification.get("type")}, step="policy_snippets")

    # Patch in type + reason
    s = await hub.get(sid)
    model = s.get_model(surface_id) if s else {}
    results = model.get("results") or []
    if results and isinstance(results, list) and isinstance(results[0], dict):
        results[0]["overview"]["type"] = classification.get("type")
        # keep backward compat with existing demo key
        results[0]["overview"]["reden"] = classification.get("reden") if "reden" in classification else classification.get("reason")
        results[0]["overview"]["snippets"] = snippets.get("snippets", [])
        await _set_results(sid, surface_id, results)

    await _set_status(sid, surface_id, loading=True, message="Juridische structuur (A2A)…", step="a2a_structure")
    await _sleep_tick()

    structured = await a2a_bez.message_send(
        "structure_bezwaar",
        {
            "raw_text": text,
            "entities": entities,
            "classification": classification,
            "snippets": snippets.get("snippets", []),
        },
    )

    # Replace full result with structured output (still under /results)
    await _set_results(
        sid,
        surface_id,
        [
            {
                "kind": "bezwaar",
                "overview": structured.get("overview", {}),
                "key_points": structured.get("key_points", []),
                "actions": structured.get("actions", []),
                "draft_response": structured.get("draft_response", ""),
            }
        ],
    )

    await _set_status(sid, surface_id, loading=True, message="Concept reactie (Gemini of fallback)…", step="draft")
    await _sleep_tick()

    # Draft already produced by agent; just flip status to done.
    await _set_status(sid, surface_id, loading=False, message="Klaar. Conceptreactie is opgesteld (demo).", step="done")
