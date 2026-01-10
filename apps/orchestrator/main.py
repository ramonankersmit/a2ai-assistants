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
            "message": "A2UI: Kies een assistent om te starten.",
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


async def _sleep_tick() -> None:
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


async def _a2a_call_with_trace(
    sid: str,
    surface_id: str,
    client: A2AClient,
    capability: str,
    payload: Json,
    *,
    step: Optional[str] = None,
) -> Json:
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
            await _send_open_surface(
                sid, "toeslagen", "Toeslagen Check",
                _empty_surface_model("A2UI: Vul de gegevens in en klik op Check."),
            )
        elif target == "bezwaar":
            await _send_open_surface(
                sid, "bezwaar", "Bezwaar Assistent",
                _empty_surface_model("A2UI: Plak een bezwaarbrief en klik op Analyseer."),
            )
        elif target == "genui_search":
            await _send_open_surface(
                sid, "genui_search", "Generatieve UI — Zoeken",
                _empty_surface_model("A2UI: Stel een vraag en klik op Zoek."),
            )
        else:
            await _send_open_surface(sid, "home", "Belastingdienst Assistants", _home_surface_model())
        return {"ok": True}

    if name == "toeslagen/check":
        asyncio.create_task(run_toeslagen_flow(sid, data))
        return {"ok": True}

    if name == "bezwaar/analyse":
        asyncio.create_task(run_bezwaar_flow(sid, data))
        return {"ok": True}

    # Idee 1 - stub flow (nog zonder MCP/A2A)
    if name == "genui/search":
        asyncio.create_task(run_genui_search_flow(sid, data))
        return {"ok": True}

    return {"ok": True, "ignored": True}


async def run_toeslagen_flow(sid: str, inputs: Json) -> None:
    surface_id = "toeslagen"

    await _send_open_surface(
        sid, "toeslagen", "Toeslagen Check",
        _empty_surface_model("A2UI: Nieuwe run gestart. Bezig met verwerken…"),
    )
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: Voorwaarden ophalen…", step="rules_lookup")
    await _sleep_tick()

    regeling = inputs.get("regeling", "Huurtoeslag")
    jaar = int(inputs.get("jaar", 2024))
    situatie = inputs.get("situatie", "Alleenstaand")
    loon_of_vermogen = bool(inputs.get("loonOfVermogen", True))

    voorwaarden = await _mcp_call_with_trace(
        sid, surface_id, "rules_lookup", {"regeling": regeling, "jaar": jaar}, step="rules_lookup"
    )
    await _set_results(sid, surface_id, [{"kind": "voorwaarden", "title": "Voorwaarden", "items": voorwaarden.get("voorwaarden", [])}])

    await _set_status(sid, surface_id, loading=True, message="A2UI: Checklist samenstellen…", step="doc_checklist")
    await _sleep_tick()

    checklist = await _mcp_call_with_trace(
        sid, surface_id, "doc_checklist", {"regeling": regeling, "situatie": situatie}, step="doc_checklist"
    )
    docs = checklist.get("documenten", [])
    await _set_results(sid, surface_id, [
        {"kind": "voorwaarden", "title": "Voorwaarden", "items": voorwaarden.get("voorwaarden", [])},
        {"kind": "documenten", "title": "Benodigde Documenten", "items": docs[:3]},
    ])

    await _set_status(sid, surface_id, loading=True, message="A2UI: Aandachtspunten berekenen…", step="risk_notes")
    await _sleep_tick()

    notes = await _mcp_call_with_trace(
        sid, surface_id, "risk_notes",
        {"regeling": regeling, "jaar": jaar, "situatie": situatie, "loonOfVermogen": loon_of_vermogen},
        step="risk_notes",
    )
    risks = notes.get("aandachtspunten", [])

    await _set_results(sid, surface_id, [
        {"kind": "voorwaarden", "title": "Voorwaarden", "items": voorwaarden.get("voorwaarden", [])},
        {"kind": "documenten", "title": "Benodigde Documenten", "items": docs},
        {"kind": "aandachtspunten", "title": "Aandachtspunten", "items": risks},
    ])

    await _set_status(sid, surface_id, loading=True, message="A2UI: Uitleg in B1 (agent)…", step="a2a_explain")
    await _sleep_tick()

    combined_items: List[Json] = [{"category": "document", "text": d} for d in docs] + [{"category": "aandachtspunt", "text": r} for r in risks]
    enriched = await _a2a_call_with_trace(
        sid, surface_id, a2a_toes, "explain_toeslagen",
        {"inputs": {"regeling": regeling, "jaar": jaar, "situatie": situatie}, "items": combined_items},
        step="a2a_explain",
    )

    await _set_results(sid, surface_id, [
        {"kind": "documenten", "title": "Benodigde Documenten", "items": docs},
        {"kind": "aandachtspunten", "title": "Aandachtspunten", "items": risks},
        {"kind": "verrijking", "title": "Verrijkte uitleg (B1)", "items": enriched.get("items", [])},
    ])

    await _set_status(sid, surface_id, loading=False, message="A2UI: Klaar. Demo-uitkomst (geen besluit).", step="done")


async def run_bezwaar_flow(sid: str, inputs: Json) -> None:
    surface_id = "bezwaar"
    text = (inputs.get("text") or "").strip()
    if not text:
        text = "Ik ben het niet eens met de naheffing van €750. Mijn inkomen is te laag voor deze aanslag. Ik vraag om herziening."

    await _send_open_surface(
        sid, "bezwaar", "Bezwaar Assistent",
        _empty_surface_model("A2UI: Nieuwe analyse gestart. Bezig met verwerken…"),
    )
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: Entiteiten extraheren…", step="extract_entities")
    await _sleep_tick()

    entities = await _mcp_call_with_trace(sid, surface_id, "extract_entities", {"text": text}, step="extract_entities")

    await _set_results(sid, surface_id, [{
        "kind": "bezwaar",
        "overview": {"datum": entities.get("datum"), "onderwerp": entities.get("onderwerp"), "bedrag": entities.get("bedrag")},
        "key_points": [],
        "actions": [],
        "draft_response": "",
    }])

    await _set_status(sid, surface_id, loading=True, message="A2UI: Zaak classificeren…", step="classify_case")
    await _sleep_tick()

    classification = await _mcp_call_with_trace(sid, surface_id, "classify_case", {"text": text}, step="classify_case")
    snippets = await _mcp_call_with_trace(sid, surface_id, "policy_snippets", {"type": classification.get("type")}, step="policy_snippets")

    structured = await _a2a_call_with_trace(
        sid, surface_id, a2a_bez, "structure_bezwaar",
        {"raw_text": text, "entities": entities, "classification": classification, "snippets": snippets.get("snippets", [])},
        step="a2a_structure",
    )

    await _set_results(sid, surface_id, [{
        "kind": "bezwaar",
        "overview": structured.get("overview", {}),
        "key_points": structured.get("key_points", []),
        "actions": structured.get("actions", []),
        "draft_source": structured.get("draft_source"),
        "draft_response": structured.get("draft_response", ""),
    }])

    await _set_status(sid, surface_id, loading=False, message="A2UI: Klaar. Conceptreactie opgesteld (demo).", step="done")


def _stub_search(query: str) -> List[Json]:
    q = (query or "").lower()
    items: List[Json] = []

    def add(title: str, url: str, snippet: str):
        items.append({"title": title, "url": url, "snippet": snippet})

    # Sources (curated)
    if any(k in q for k in ["bezwaar", "aanslag", "beroep"]):
        add("Hoe maak ik bezwaar?", "https://www.belastingdienst.nl/wps/wcm/connect/nl/bezwaar-en-beroep/content/eisen-bezwaar",
            "Binnen 6 weken bezwaar maken; online/formulier/brief, afhankelijk van situatie.")
        add("Bezwaarcheck inkomstenbelasting", "https://www.belastingdienst.nl/wps/wcm/connect/nl/bezwaar-en-beroep/content/hulpmiddel-bezwaarcheck-inkomstenbelasting",
            "Hulpmiddel om te bepalen of u bezwaar moet indienen en waar u het formulier vindt.")
        add("Bezwaar en uitstel van betaling", "https://www.belastingdienst.nl/wps/wcm/connect/nl/bezwaar-en-beroep/content/bezwaar-en-uitstel-van-betaling",
            "Voor het betwiste deel krijgt u uitstel van betaling tot uitspraak op bezwaar.")

    if any(k in q for k in ["betalingsregeling", "uitstel", "betalen", "niet op tijd"]):
        add("Ik kan mijn belasting niet op tijd betalen", "https://www.belastingdienst.nl/wps/wcm/connect/nl/betalenenontvangen/content/ik-kan-mijn-belasting-niet-op-tijd-betalen-uitstel-betalingsregeling",
            "U kunt uitstel of een betalingsregeling aanvragen; soms online, soms via formulier.")
        add("Verzoek betalingsregeling voor particulieren", "https://www.belastingdienst.nl/wps/wcm/connect/bldcontentnl/themaoverstijgend/programmas_en_formulieren/verzoek-betalingsregeling-voor-particulieren",
            "Formulier om een betalingsregeling aan te vragen als u niet op tijd kunt betalen.")

    if any(k in q for k in ["huurtoeslag", "toeslag", "huur"]):
        add("Voorwaarden huurtoeslag", "https://www.belastingdienst.nl/wps/wcm/connect/bldcontentnl/belastingdienst/prive/toeslagen/huurtoeslag/voorwaarden/voorwaarden",
            "Belangrijkste voorwaarden: leeftijd, inkomen/vermogen, woningtype en huurbetaling aantonen.")
        add("Kan ik huurtoeslag krijgen?", "https://www.belastingdienst.nl/wps/wcm/connect/nl/huurtoeslag/content/kan-ik-huurtoeslag-krijgen",
            "Overzicht voorwaarden en proefberekening (inkomen/vermogen/huur/huishouden).")

    if not items:
        # Default helpful sources
        add("Bezwaar, beroep en klacht", "https://www.belastingdienst.nl/wps/wcm/connect/nl/bezwaar-en-beroep/bezwaar-en-beroep",
            "Overzicht bezwaar maken, wanneer u iets hoort, mondeling toelichten, beroep, etc.")
        add("Huurtoeslag", "https://www.belastingdienst.nl/wps/wcm/connect/nl/huurtoeslag/huurtoeslag",
            "Startpunt huurtoeslag: voorwaarden, aanvragen, proefberekening.")
        add("Betalen en ontvangen", "https://www.belastingdienst.nl/wps/wcm/connect/nl/betalenenontvangen/content/betalenenontvangen",
            "Algemene informatie over betalen, uitstel en betalingsregelingen.")

    return items[:5]


async def run_genui_search_flow(sid: str, inputs: Json) -> None:
    """
    Idee 1 (Stap 1.1): deterministische stub-search + UI-blokken.
    In volgende stappen vervangen we stub-search door MCP bd_search en UI-compositie door A2A compose_ui.
    """
    surface_id = "genui_search"
    query = str(inputs.get("query", "")).strip()
    if not query:
        return

    await _send_open_surface(
        sid, surface_id, "Generatieve UI — Zoeken",
        _empty_surface_model("A2UI: Nieuwe zoekrun gestart…"),
    )
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: Zoekopdracht ontvangen…", step="start")
    await _set_results(sid, surface_id, [])
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: Bronnen selecteren (stub)…", step="select_sources")
    await _sleep_tick()

    citations = _stub_search(query)
    await _set_results(sid, surface_id, [{
        "kind": "citations",
        "title": "Bronnen (demo-stub)",
        "items": citations
    }])
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: UI-blokken samenstellen…", step="compose_blocks")
    await _sleep_tick()

    blocks: List[Json] = [
        {
            "kind": "callout",
            "title": "Kern (demo)",
            "body": (
                f"Vraag: {query}\n\n"
                "Deze tegel demonstreert het A2UI-concept: de backend stuurt UI als data (blokken), "
                "en de web-shell rendert die veilig met vaste componenten."
            ),
        },
        {
            "kind": "citations",
            "title": "Bronnen",
            "items": citations,
        },
        {
            "kind": "accordion",
            "title": "Veelgestelde vragen (demo)",
            "items": [
                {"q": "Wat is dit precies?", "a": "Een on-the-fly UI die wordt opgebouwd uit blokken (A2UI). In stap 1.2 komt echte zoeklogica via MCP."},
                {"q": "Waarom blokken i.p.v. vrije HTML?", "a": "Veiligheid en consistentie: de UI blijft Belastingdienst-stijl, terwijl de agent alleen gestructureerde output levert."},
            ],
        },
        {
            "kind": "next_questions",
            "title": "Vervolgvraag",
            "items": [
                "Hoe maak ik bezwaar?",
                "Ik kan niet op tijd betalen — betalingsregeling?",
                "Kan ik huurtoeslag krijgen?",
            ],
        },
        {
            "kind": "notice",
            "title": "Let op",
            "body": "Stap 1.1 gebruikt een stub-search. Volgende stap: MCP bd_search (curated dataset). Daarna: A2A compose_ui (LLM bepaalt blokken).",
        },
    ]
    await _set_results(sid, surface_id, blocks)
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=False, message="A2UI: Klaar. (Idee 1 · Stap 1.1)", step="done")
