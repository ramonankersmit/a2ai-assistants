# DROP-IN replacement for apps/orchestrator/main.py (Idea 1 Step 1.2)
# Uses MCP tool bd_search instead of stub search.

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
        "status": {"loading": False, "message": "A2UI: Kies een assistent om te starten.", "step": "idle", "lastRefresh": now_iso()},
        "results": [],
    }


def _empty_surface_model(message: str) -> Json:
    return {
        "status": {"loading": False, "message": message, "step": "idle", "lastRefresh": now_iso()},
        "results": [],
    }


async def _send_open_surface(sid: str, surface_id: str, title: str, initial_model: Json) -> None:
    s = await hub.get(sid)
    if not s:
        return
    s.models[surface_id] = initial_model
    await hub.push(sid, surface_open(surface_id, title, initial_model))


async def _set_status(sid: str, surface_id: str, *, loading: Optional[bool] = None, message: Optional[str] = None, step: Optional[str] = None) -> None:
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


async def _sleep_tick() -> None:
    await asyncio.sleep(0.6)


def _ms(dt_seconds: float) -> int:
    return int(round(dt_seconds * 1000))


async def _mcp_call_with_trace(sid: str, surface_id: str, tool_name: str, args: Json, *, step: Optional[str] = None) -> Json:
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


async def _a2a_call_with_trace(sid: str, surface_id: str, client: A2AClient, capability: str, payload: Json, *, step: Optional[str] = None) -> Json:
    t0 = time.perf_counter()
    try:
        result = await client.message_send(capability, payload)
        dt = _ms(time.perf_counter() - t0)
        await _set_status(sid, surface_id, loading=True, message=f"A2A: {capability} ({dt}ms)", step=step or capability)
        return result
    except Exception:
        dt = _ms(time.perf_counter() - t0)
        await _set_status(sid, surface_id, loading=True, message=f"A2A: {capability} mislukt ({dt}ms)", step=step or capability)
        raise


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/events")
async def events(request: Request):
    session = await hub.create()

    async def gen():
        yield f"data: {JSONResponse(content={'kind':'session/created','sessionId':session.session_id}).body.decode('utf-8')}\n\n"
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
    data = payload.get("payload") or {}

    if name == "nav/open":
        target = data.get("surfaceId")
        if target == "toeslagen":
            await _send_open_surface(sid, "toeslagen", "Toeslagen Check", _empty_surface_model("A2UI: Vul de gegevens in en klik op Check."))
        elif target == "bezwaar":
            await _send_open_surface(sid, "bezwaar", "Bezwaar Assistent", _empty_surface_model("A2UI: Plak een bezwaarbrief en klik op Analyseer."))
        elif target == "genui_search":
            await _send_open_surface(sid, "genui_search", "Generatieve UI — Zoeken", _empty_surface_model("A2UI: Stel een vraag en klik op Zoek."))
        else:
            await _send_open_surface(sid, "home", "Belastingdienst Assistants", _home_surface_model())
        return {"ok": True}

    if name == "toeslagen/check":
        asyncio.create_task(run_toeslagen_flow(sid, data))
        return {"ok": True}

    if name == "bezwaar/analyse":
        asyncio.create_task(run_bezwaar_flow(sid, data))
        return {"ok": True}

    if name == "genui/search":
        asyncio.create_task(run_genui_search_flow(sid, data))
        return {"ok": True}

    return {"ok": True, "ignored": True}


# ---- existing flows (copy/paste from your current main.py) ----
# Keep your current run_toeslagen_flow and run_bezwaar_flow as-is.
# This file includes only Idea 1 Step 1.2 additions below.

def _faq_for(query: str) -> List[Json]:
    q = (query or "").lower()
    if "bezwaar" in q:
        return [
            {"q": "Binnen welke termijn kan ik bezwaar maken?", "a": "Meestal binnen 6 weken (situatie-afhankelijk). Controleer de bronpagina."},
            {"q": "Wat moet er in een bezwaar staan?", "a": "In elk geval kenmerk/aanslagnummer, datum en motivatie (placeholders in demo)."},
        ]
    if "betal" in q or "uitstel" in q:
        return [
            {"q": "Kan ik uitstel of een regeling aanvragen?", "a": "Vaak wel: online of via formulier, afhankelijk van situatie."},
            {"q": "Welke gegevens heb ik nodig?", "a": "Vaak: openstaand bedrag, termijnvoorkeur, en inzicht in inkomsten/uitgaven."},
        ]
    if "huurtoeslag" in q or "toeslag" in q:
        return [
            {"q": "Welke voorwaarden gelden meestal?", "a": "Inkomen/vermogen, huur/huishouden en jaar/situatie zijn bepalend. Check de officiële pagina."},
            {"q": "Welke documenten zijn vaak nodig?", "a": "Bijv. huurgegevens en bewijs van inkomen/vermogen (afhankelijk van situatie)."},
        ]
    return [
        {"q": "Wat laat deze tegel zien?", "a": "De UI wordt opgebouwd uit blokken op basis van data (A2UI)."},
        {"q": "Waarom niet direct HTML genereren?", "a": "Veiligheid/consistentie: alleen whitelisted blokken worden gerenderd."},
    ]


def _next_questions_for(query: str) -> List[str]:
    q = (query or "").lower()
    if "bezwaar" in q:
        return ["Welke gegevens moet ik meesturen?", "Kan ik uitstel van betaling krijgen bij bezwaar?", "Hoe lang duurt een bezwaarprocedure?"]
    if "betal" in q or "uitstel" in q:
        return ["Hoe vraag ik een betalingsregeling aan?", "Welke termijnen zijn mogelijk?", "Wat als ik niets doe?"]
    if "toeslag" in q:
        return ["Kan ik huurtoeslag krijgen?", "Welke inkomensgrenzen gelden?", "Wat moet ik doorgeven als mijn situatie wijzigt?"]
    return ["Hoe maak ik bezwaar?", "Ik kan niet op tijd betalen — betalingsregeling?", "Kan ik huurtoeslag krijgen?"]


async def run_genui_search_flow(sid: str, inputs: Json) -> None:
    surface_id = "genui_search"
    query = str(inputs.get("query", "")).strip()
    if not query:
        return

    await _send_open_surface(sid, surface_id, "Generatieve UI — Zoeken", _empty_surface_model("A2UI: Nieuwe zoekrun gestart…"))
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: Zoekopdracht ontvangen…", step="start")
    await _set_results(sid, surface_id, [])
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: Bronnen ophalen (MCP)…", step="bd_search")
    await _sleep_tick()

    search_resp = await _mcp_call_with_trace(sid, surface_id, "bd_search", {"query": query, "k": 5}, step="bd_search")
    citations = search_resp.get("items", []) if isinstance(search_resp, dict) else []

    await _set_results(sid, surface_id, [{"kind": "citations", "title": "Bronnen (MCP)", "items": citations}])
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: UI-blokken samenstellen (deterministisch)…", step="compose_blocks")
    await _sleep_tick()

    top = citations[0] if citations else {}
    top_title = str(top.get("title", ""))
    top_snip = str(top.get("snippet", ""))

    blocks: List[Json] = [
        {
            "kind": "callout",
            "title": "Kern (demo)",
            "body": (
                f"Vraag: {query}\n\n"
                + (f"Top-bron: {top_title}\n{top_snip}\n\n" if top_title else "")
                + "Dit is stap 1.2: zoekresultaten komen uit MCP (deterministisch) en de UI rendert blokken op basis van data.\n"
                  "In stap 1.3 laat een LLM (A2A) bepalen welke blokken worden getoond."
            ),
        },
        {"kind": "citations", "title": "Bronnen", "items": citations},
        {"kind": "accordion", "title": "Veelgestelde vragen (demo)", "items": _faq_for(query)},
        {"kind": "next_questions", "title": "Vervolgvraag", "items": _next_questions_for(query)},
        {"kind": "notice", "title": "Let op", "body": "Dit is demo-informatie. Raadpleeg altijd de officiële pagina’s voor actuele details."},
    ]
    await _set_results(sid, surface_id, blocks)
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=False, message="A2UI: Klaar. (Idee 1 · Stap 1.2)", step="done")
