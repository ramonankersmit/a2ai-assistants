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
A2A_GENUI_URL = os.getenv("A2A_GENUI_URL", "http://localhost:8030/")

hub = SessionHub()
mcp = MCPClient(MCP_SSE_URL)
a2a_toes = A2AClient(A2A_TOESLAGEN_URL)
a2a_bez = A2AClient(A2A_BEZWAAR_URL)
a2a_genui = A2AClient(A2A_GENUI_URL)

app = FastAPI(title="Belastingdienst Assistants Orchestrator", version="0.1.6")

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
            "source": "",
            "sourceReason": "",
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
            "source": "",
            "sourceReason": "",
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
    source: Optional[str] = None,
    sourceReason: Optional[str] = None,
) -> None:
    patches: List[Json] = []
    if loading is not None:
        patches.append({"op": "replace", "path": "/status/loading", "value": loading})
    if message is not None:
        patches.append({"op": "replace", "path": "/status/message", "value": message})
    if step is not None:
        patches.append({"op": "replace", "path": "/status/step", "value": step})
    if source is not None:
        patches.append({"op": "replace", "path": "/status/source", "value": source})
    if sourceReason is not None:
        patches.append({"op": "replace", "path": "/status/sourceReason", "value": sourceReason})
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
    result = await mcp.call_tool(tool_name, args)
    dt = _ms(time.perf_counter() - t0)
    await _set_status(sid, surface_id, loading=True, message=f"MCP: {tool_name} ({dt}ms)", step=step or tool_name)
    return result


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
    result = await client.message_send(capability, payload)
    dt = _ms(time.perf_counter() - t0)
    await _set_status(sid, surface_id, loading=True, message=f"A2A: {capability} ({dt}ms)", step=step or capability)
    return result


# -----------------------
# GenUI: defensive block validation (whitelist)
# -----------------------

GENUI_ALLOWED_KINDS = {"callout", "citations", "accordion", "next_questions", "notice", "decision", "form"}


def _safe_str(value: Any, *, max_len: int = 4000) -> str:
    s = "" if value is None else str(value)
    s = s.strip()
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def _a2a_data_dict(resp: Any) -> Dict[str, Any]:
    """Extract a dict payload from multiple possible A2A client response shapes."""
    if not isinstance(resp, dict):
        return {}
    data = resp.get("data")
    if isinstance(data, dict):
        return data
    result = resp.get("result")
    if isinstance(result, dict):
        return result
    payload = resp.get("payload")
    if isinstance(payload, dict):
        return payload
    # Last resort: treat the top-level dict as payload
    return resp



def _sanitize_citations_items(items: Any, *, max_items: int = 10) -> List[Json]:
    out: List[Json] = []
    if not isinstance(items, list):
        return out
    for it in items[:max_items]:
        if not isinstance(it, dict):
            continue
        out.append(
            {
                "title": _safe_str(it.get("title") or it.get("url") or ""),
                "url": _safe_str(it.get("url") or ""),
                "snippet": _safe_str(it.get("snippet") or "", max_len=800),
            }
        )
    return out


def _sanitize_qa_items(items: Any, *, max_items: int = 8) -> List[Json]:
    out: List[Json] = []
    if not isinstance(items, list):
        return out
    for it in items[:max_items]:
        if not isinstance(it, dict):
            continue
        q = _safe_str(it.get("q") or it.get("question") or "", max_len=300)
        a = _safe_str(it.get("a") or it.get("answer") or "", max_len=2000)
        if not q and not a:
            continue
        out.append({"q": q, "a": a})
    return out


def _sanitize_next_questions(items: Any, *, max_items: int = 8) -> List[str]:
    out: List[str] = []
    if not isinstance(items, list):
        return out
    for it in items[:max_items]:
        q = _safe_str(it, max_len=200)
        if q:
            out.append(q)
    return out


def _sanitize_decision_options(options: Any, *, max_items: int = 6) -> List[str]:
    out: List[str] = []
    if isinstance(options, list):
        for it in options[:max_items]:
            if isinstance(it, dict):
                label = _safe_str(it.get("label") or it.get("text") or it.get("value") or "", max_len=80)
            else:
                label = _safe_str(it, max_len=80)
            if label:
                out.append(label)
    return out



def _sanitize_form_fields(fields: Any, *, max_fields: int = 10) -> List[Json]:
    out: List[Json] = []
    if not isinstance(fields, list):
        return out
    for f in fields[:max_fields]:
        if not isinstance(f, dict):
            continue
        fid = _safe_str(f.get("id") or "", max_len=40)
        if not fid:
            continue
        ftype = _safe_str(f.get("type") or "text", max_len=20).lower()
        if ftype not in ("text", "number", "date", "email", "textarea", "select"):
            ftype = "text"

        options = f.get("options") or []
        if not isinstance(options, list):
            options = []
        options_s: List[str] = []
        for o in options[:12]:
            label = _safe_str(o, max_len=80)
            if label:
                options_s.append(label)

        out.append(
            {
                "id": fid,
                "label": _safe_str(f.get("label") or fid, max_len=120),
                "type": ftype,
                "required": bool(f.get("required", False)),
                "placeholder": _safe_str(f.get("placeholder") or "", max_len=160),
                "pattern": _safe_str(f.get("pattern") or "", max_len=120),
                "min": f.get("min"),
                "max": f.get("max"),
                "minLength": f.get("minLength"),
                "maxLength": f.get("maxLength"),
                "options": options_s,
            }
        )
    return out


def _sanitize_genui_blocks(blocks: Any, *, max_blocks: int = 12) -> List[Json]:
    """Accept only known block kinds and coerce fields to a safe shape."""
    if not isinstance(blocks, list):
        return []

    out: List[Json] = []
    for b in blocks[:max_blocks]:
        if not isinstance(b, dict):
            continue
        kind = _safe_str(b.get("kind") or "").lower()
        if kind not in GENUI_ALLOWED_KINDS:
            continue

        if kind == "callout":
            out.append(
                {
                    "kind": "callout",
                    "title": _safe_str(b.get("title") or "Kern", max_len=140),
                    "body": _safe_str(b.get("body") or b.get("text") or "", max_len=4000),
                }
            )
            continue

        if kind == "citations":
            out.append(
                {
                    "kind": "citations",
                    "title": _safe_str(b.get("title") or "Bronnen", max_len=140),
                    "items": _sanitize_citations_items(b.get("items") or []),
                }
            )
            continue

        if kind == "accordion":
            out.append(
                {
                    "kind": "accordion",
                    "title": _safe_str(b.get("title") or "Veelgestelde vragen", max_len=140),
                    "items": _sanitize_qa_items(b.get("items") or []),
                }
            )
            continue

        if kind == "next_questions":
            out.append(
                {
                    "kind": "next_questions",
                    "title": _safe_str(b.get("title") or "Vervolgvraag", max_len=140),
                    "items": _sanitize_next_questions(b.get("items") or []),
                }
            )
            continue


        if kind == "decision":
            out.append(
                {
                    "kind": "decision",
                    "title": _safe_str(b.get("title") or "Keuze", max_len=140),
                    "question": _safe_str(b.get("question") or b.get("q") or "Kies een optie", max_len=240),
                    "options": _sanitize_decision_options(b.get("options") or b.get("items") or []),
                }
            )
            continue



        if kind == "form":
            out.append(
                {
                    "kind": "form",
                    "title": _safe_str(b.get("title") or "Formulier", max_len=140),
                    "formId": _safe_str(b.get("formId") or b.get("id") or "form", max_len=40),
                    "description": _safe_str(b.get("description") or "", max_len=400),
                    "submitLabel": _safe_str(b.get("submitLabel") or "Verstuur", max_len=60),
                    "fields": _sanitize_form_fields(b.get("fields") or []),
                }
            )
            continue


        if kind == "notice":
            out.append(
                {
                    "kind": "notice",
                    "title": _safe_str(b.get("title") or "Let op", max_len=140),
                    "body": _safe_str(b.get("body") or "", max_len=1200),
                }
            )
            continue

    return out


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
        elif target == "genui_form":
            await _send_open_surface(sid, "genui_form", "Generatieve UI — Formulier", _empty_surface_model("A2UI: Stel een vraag en klik op Genereer formulier."))
        elif target == "genui_tree":
            await _send_open_surface(sid, "genui_tree", "Generatieve UI — Wizard", _empty_surface_model("A2UI: Start de wizard…"))
            asyncio.create_task(run_genui_tree_start_flow(sid, {}))
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

    if name == "genui/form_generate":
        asyncio.create_task(run_genui_form_generate_flow(sid, data))
        return {"ok": True}

    if name == "genui/form_submit":
        asyncio.create_task(run_genui_form_submit_flow(sid, data))
        return {"ok": True}

    if name == "genui/form_change":
        asyncio.create_task(run_genui_form_change_flow(sid, data))
        return {"ok": True}

    if name == "genui_tree/start":
        asyncio.create_task(run_genui_tree_start_flow(sid, data))
        return {"ok": True}

    if name == "genui_tree/choose":
        asyncio.create_task(run_genui_tree_choose_flow(sid, data))
        return {"ok": True}

    return {"ok": True, "ignored": True}


# -----------------------
# Flow 1: Toeslagen (MCP + A2A toeslagen)
# -----------------------

async def run_toeslagen_flow(sid: str, inputs: Json) -> None:
    surface_id = "toeslagen"
    await _send_open_surface(sid, surface_id, "Toeslagen Check", _empty_surface_model("A2UI: Nieuwe run gestart. Bezig met verwerken…"))
    await _sleep_tick()

    regeling = inputs.get("regeling", "Huurtoeslag")
    jaar = int(inputs.get("jaar", 2024))
    situatie = inputs.get("situatie", "Alleenstaand")
    loon_of_vermogen = bool(inputs.get("loonOfVermogen", True))

    await _set_status(sid, surface_id, loading=True, message="A2UI: Voorwaarden ophalen (MCP)…", step="rules_lookup")
    await _sleep_tick()
    voorwaarden = await _mcp_call_with_trace(sid, surface_id, "rules_lookup", {"regeling": regeling, "jaar": jaar}, step="rules_lookup")

    await _set_status(sid, surface_id, loading=True, message="A2UI: Checklist samenstellen…", step="doc_checklist")
    await _sleep_tick()
    checklist = await _mcp_call_with_trace(sid, surface_id, "doc_checklist", {"regeling": regeling, "situatie": situatie}, step="doc_checklist")
    docs = checklist.get("documenten", [])

    await _set_results(sid, surface_id, [{"kind": "documenten", "title": "Benodigde Documenten", "items": docs[:3]}])
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: Aandachtspunten berekenen…", step="risk_notes")
    await _sleep_tick()
    notes = await _mcp_call_with_trace(
        sid, surface_id, "risk_notes",
        {"regeling": regeling, "jaar": jaar, "situatie": situatie, "loonOfVermogen": loon_of_vermogen},
        step="risk_notes",
    )
    risks = notes.get("aandachtspunten", [])

    await _set_results(sid, surface_id, [
        {"kind": "documenten", "title": "Benodigde Documenten", "items": docs},
        {"kind": "aandachtspunten", "title": "Aandachtspunten", "items": risks},
    ])
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: Uitleg in B1 (A2A)…", step="explain_toeslagen")
    await _sleep_tick()

    combined_items: List[Json] = [{"category": "document", "text": d} for d in docs] + [{"category": "aandachtspunt", "text": r} for r in risks]
    enriched = await _a2a_call_with_trace(
        sid,
        surface_id,
        a2a_toes,
        "explain_toeslagen",
        {"inputs": {"regeling": regeling, "jaar": jaar, "situatie": situatie, "voorwaarden": voorwaarden.get("voorwaarden", [])}, "items": combined_items},
        step="explain_toeslagen",
    )

    await _set_results(sid, surface_id, [
        {"kind": "documenten", "title": "Benodigde Documenten", "items": docs},
        {"kind": "aandachtspunten", "title": "Aandachtspunten", "items": risks},
        {"kind": "verrijking", "title": "Verrijking (B1 + prioriteit)", "items": enriched.get("items", [])},
    ])
    await _set_status(sid, surface_id, loading=False, message="A2UI: Klaar. Demo-uitkomst (geen besluit).", step="done")


# -----------------------
# Flow 2: Bezwaar (MCP + A2A bezwaar)
# -----------------------

async def run_bezwaar_flow(sid: str, inputs: Json) -> None:
    surface_id = "bezwaar"
    text = (inputs.get("text") or "").strip() or "Ik ben het niet eens met de naheffing van €750. Mijn inkomen is te laag voor deze aanslag. Ik vraag om herziening."

    await _send_open_surface(sid, surface_id, "Bezwaar Assistent", _empty_surface_model("A2UI: Nieuwe analyse gestart. Bezig met verwerken…"))
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: Entiteiten extraheren (MCP)…", step="extract_entities")
    await _sleep_tick()
    entities = await _mcp_call_with_trace(sid, surface_id, "extract_entities", {"text": text}, step="extract_entities")

    await _set_status(sid, surface_id, loading=True, message="A2UI: Zaak classificeren (MCP)…", step="classify_case")
    await _sleep_tick()
    classification = await _mcp_call_with_trace(sid, surface_id, "classify_case", {"text": text}, step="classify_case")

    await _set_status(sid, surface_id, loading=True, message="A2UI: Beleidsnippets ophalen (MCP)…", step="policy_snippets")
    await _sleep_tick()
    snippets = await _mcp_call_with_trace(sid, surface_id, "policy_snippets", {"type": classification.get("type")}, step="policy_snippets")

    await _set_status(sid, surface_id, loading=True, message="A2UI: Juridische structuur (A2A)…", step="structure_bezwaar")
    await _sleep_tick()
    structured = await _a2a_call_with_trace(
        sid,
        surface_id,
        a2a_bez,
        "structure_bezwaar",
        {"raw_text": text, "entities": entities, "classification": classification, "snippets": snippets.get("snippets", [])},
        step="structure_bezwaar",
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


# -----------------------
# Flow 3: GenUI Search (MCP bd_search + A2A compose_ui)
# -----------------------

async def run_genui_search_flow(sid: str, inputs: Json) -> None:
    surface_id = "genui_search"
    query = str(inputs.get("query", "")).strip()
    if not query:
        return

    await _send_open_surface(sid, surface_id, "Generatieve UI — Zoeken", _empty_surface_model("A2UI: Nieuwe zoekrun gestart…"))
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: Zoekopdracht ontvangen…", step="start", source="", sourceReason="")
    await _set_results(sid, surface_id, [])
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: Bronnen ophalen (MCP)…", step="bd_search")
    await _sleep_tick()

    search_resp = await _mcp_call_with_trace(sid, surface_id, "bd_search", {"query": query, "k": 5}, step="bd_search")
    citations = search_resp.get("items", []) if isinstance(search_resp, dict) else []

    citations_block: Json = {"kind": "citations", "title": "Bronnen (MCP)", "items": citations}

    # progressive: show citations first
    await _set_results(sid, surface_id, [citations_block])
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: UI-plan maken (A2A)…", step="compose_ui")
    await _sleep_tick()

    try:
        ui_raw = await _a2a_call_with_trace(
            sid,
            surface_id,
            a2a_genui,
            "compose_ui",
            {"query": query, "citations": citations},
            step="compose_ui",
        )

        # GenUI agent returns {"status":"ok","data":{...}}
        ui_data = ui_raw.get("data") if isinstance(ui_raw, dict) and isinstance(ui_raw.get("data"), dict) else ui_raw
        if not isinstance(ui_data, dict):
            ui_data = {}

        blocks_raw = ui_data.get("blocks", [])
        blocks = _sanitize_genui_blocks(blocks_raw)

        # Prefer a single citations block from MCP (avoid duplicates from the agent output)
        blocks = [b for b in blocks if b.get("kind") != "citations"]

        ui_source = _safe_str(ui_data.get("ui_source", "unknown"), max_len=40).lower()
        if ui_source not in ("gemini", "fallback"):
            ui_source = "unknown"
        ui_reason = _safe_str(ui_data.get("ui_source_reason", ""), max_len=80)

        await _set_status(sid, surface_id, source=ui_source, sourceReason=ui_reason)

        merged: List[Json] = []
        if citations:
            merged.append(citations_block)
        merged.extend(blocks)

        if len(merged) == (1 if citations else 0):
            merged.append({"kind": "notice", "title": "GenUI", "body": "Geen GenUI-blokken gegenereerd; alleen bronnen getoond (demo)."})
        await _set_results(sid, surface_id, merged)

        await _set_status(sid, surface_id, loading=False, message="A2UI: Klaar. (GenUI)", step="done")
    except Exception:
        await _set_status(sid, surface_id, source="fallback", sourceReason="a2a_down_or_error")

        merged: List[Json] = []
        if citations:
            merged.append(citations_block)
        merged.append({"kind": "notice", "title": "GenUI", "body": "A2A genui-agent niet bereikbaar; fallback actief."})
        await _set_results(sid, surface_id, merged)

        await _set_status(sid, surface_id, loading=False, message="A2UI: Klaar. (GenUI fallback)", step="done")


# -----------------------
# Flow 4: GenUI Wizard (Decision Tree) — deterministic A2A (next_node) + MCP citations
# -----------------------

def _tree_default_state() -> Json:
    return {"node": "root", "path": []}


async def _set_tree_state(sid: str, surface_id: str, state: Json) -> None:
    await hub.push_update_and_apply(sid, surface_id, [{"op": "replace", "path": "/tree", "value": state}])


def _tree_query_from_state(state: Json, choice: str) -> str:
    # Derive a deterministic query for bd_search based on the path + current choice.
    parts: List[str] = []
    for p in (state.get("path") or []):
        if p:
            parts.append(str(p))
    if choice:
        parts.append(choice)

    q = " ".join(parts).strip()
    q_low = q.lower()

    # Light boosts for better hits in the curated dataset
    if "bezwaar" in q_low:
        q = f"{q} bezwaar indienen termijn"
    if "betal" in q_low or "uitstel" in q_low:
        q = f"{q} uitstel betalingsregeling"
    if "toeslag" in q_low:
        q = f"{q} toeslagen wijzigen terugbetalen"
    if not q:
        q = "bezwaar betalen toeslagen"

    return q


async def run_genui_tree_start_flow(sid: str, inputs: Json) -> None:
    surface_id = "genui_tree"

    # Do not depend on Gemini; start always deterministic.
    await _send_open_surface(sid, surface_id, "Generatieve UI — Wizard", _empty_surface_model("A2UI: Wizard gestart."))
    await _sleep_tick()

    state = _tree_default_state()
    await _set_tree_state(sid, surface_id, state)

    await _set_status(
        sid,
        surface_id,
        loading=True,
        message="A2UI: Wizard laden…",
        step="tree_start",
        source="fallback",
        sourceReason="deterministic_tree",
    )
    await _set_results(sid, surface_id, [])
    await _sleep_tick()

    blocks: List[Json] = [
        {
            "kind": "callout",
            "title": "Wizard (demo)",
            "body": "Beantwoord een paar korte vragen. Op basis daarvan tonen we relevante info en vervolgstappen (demo, geen besluit).",
        },
        {
            "kind": "decision",
            "title": "Stap 1",
            "question": "Waar gaat uw vraag over?",
            "options": ["Bezwaar maken", "Betalen", "Toeslagen", "Contact", "Anders"],
        },
    ]

    await _set_results(sid, surface_id, blocks)
    await _set_status(sid, surface_id, loading=False, message="A2UI: Kies een optie om door te gaan.", step="waiting")


async def run_genui_tree_choose_flow(sid: str, inputs: Json) -> None:
    surface_id = "genui_tree"
    choice = _safe_str(inputs.get("option") or inputs.get("choice") or inputs.get("value") or "", max_len=120)
    if not choice:
        return

    s = await hub.get(sid)
    if not s:
        return
    model = s.get_model(surface_id) if s else {}
    state = model.get("tree") if isinstance(model, dict) else None
    if not isinstance(state, dict):
        state = _tree_default_state()

    # Update the visible path immediately (UX): show the chosen option in the path while we work.
    try:
        path_in = state.get("path") or []
        path = [str(x) for x in path_in if str(x).strip()]
        if choice and (not path or path[-1] != choice):
            path = (path + [choice])[:12]
        preview_state = {**state, "path": path}
        await _set_tree_state(sid, surface_id, preview_state)
    except Exception:
        # Never break the demo on UI-only enhancements.
        pass

    await _set_status(sid, surface_id, loading=True, message=f"A2UI: Keuze ontvangen: {choice}", step="tree_choose")
    await _sleep_tick()

    # 1) MCP citations for this step (deterministic)
    query = _tree_query_from_state(state, choice)
    await _set_status(sid, surface_id, loading=True, message="A2UI: Bronnen ophalen (MCP)…", step="bd_search")
    await _sleep_tick()

    search_resp = await _mcp_call_with_trace(sid, surface_id, "bd_search", {"query": query, "k": 5}, step="bd_search")
    citations = search_resp.get("items", []) if isinstance(search_resp, dict) else []
    citations_block: Json = {"kind": "citations", "title": "Bronnen (MCP)", "items": citations}

    # Progressive: show citations first
    await _set_results(sid, surface_id, [citations_block] if citations else [])
    await _sleep_tick()

    # 2) A2A decision step (deterministic fallback inside the GenUI agent)
    await _set_status(sid, surface_id, loading=True, message="A2UI: Volgende stap bepalen (A2A)…", step="next_node")
    await _sleep_tick()

    try:
        ui_raw = await _a2a_call_with_trace(
            sid,
            surface_id,
            a2a_genui,
            "next_node",
            {"state": state, "choice": choice, "citations": citations},
            step="next_node",
        )

        ui_data = ui_raw.get("data") if isinstance(ui_raw, dict) and isinstance(ui_raw.get("data"), dict) else ui_raw
        if not isinstance(ui_data, dict):
            ui_data = {}

        blocks_raw = ui_data.get("blocks", [])
        blocks = _sanitize_genui_blocks(blocks_raw)

        # Prefer citations from MCP only
        blocks = [b for b in blocks if b.get("kind") != "citations"]

        ui_source = _safe_str(ui_data.get("ui_source", "fallback"), max_len=40).lower()
        if ui_source not in ("gemini", "fallback"):
            ui_source = "fallback"
        ui_reason = _safe_str(ui_data.get("ui_source_reason", "deterministic_tree"), max_len=80)

        new_state = ui_data.get("tree")
        if isinstance(new_state, dict):
            await _set_tree_state(sid, surface_id, new_state)

        await _set_status(sid, surface_id, source=ui_source, sourceReason=ui_reason)

        merged: List[Json] = []
        if citations:
            merged.append(citations_block)
        merged.extend(blocks)

        if not blocks:
            merged.append({"kind": "notice", "title": "Wizard", "body": "Geen blokken ontvangen; alleen bronnen getoond (demo)."})
        await _set_results(sid, surface_id, merged)

        has_decision = any(b.get("kind") == "decision" for b in merged)
        await _set_status(
            sid,
            surface_id,
            loading=False,
            message="A2UI: Kies een optie om door te gaan." if has_decision else "A2UI: Klaar. (wizard, demo)",
            step="waiting" if has_decision else "done",
        )
    except Exception:
        await _set_status(sid, surface_id, source="fallback", sourceReason="a2a_down_or_error")

        merged: List[Json] = []
        if citations:
            merged.append(citations_block)
        merged.append({"kind": "notice", "title": "Wizard", "body": "A2A genui-agent niet bereikbaar; wizard valt terug op start."})
        merged.append(
            {
                "kind": "decision",
                "title": "Stap 1",
                "question": "Waar gaat uw vraag over?",
                "options": ["Bezwaar maken", "Betalen", "Toeslagen", "Contact", "Anders"],
            }
        )
        await _set_results(sid, surface_id, merged)
        await _set_status(sid, surface_id, loading=False, message="A2UI: Kies een optie om door te gaan.", step="waiting")

# -----------------------
# Flow 5: GenUI Form (Form-on-the-fly) — deterministic A2A (compose_form/explain_form) + MCP validate_form
# -----------------------

def _form_default_state() -> Json:
    return {"query": "", "citations": [], "form": None}


async def _set_form_state(sid: str, surface_id: str, state: Json) -> None:
    await hub.push_update_and_apply(sid, surface_id, [{"op": "replace", "path": "/form", "value": state}])


def _extract_first_form_block(blocks: List[Json]) -> Optional[Json]:
    for b in blocks:
        if isinstance(b, dict) and b.get("kind") == "form":
            return b
    return None


def _boost_query(query: str) -> str:
    """Deterministische query-expansie (veilig), zodat bd_search vaker relevante hits heeft."""
    q = (query or "").strip()
    if not q:
        return ""

    low = q.lower()
    expansions: list[str] = []

    if any(k in low for k in ["bezwaar", "bezwaarschrift", "beroep"]):
        expansions += ["bezwaar indienen", "termijn", "uitspraak op bezwaar"]

    if any(k in low for k in ["uitstel", "betalingsregeling", "betaal", "betalen", "incasso"]):
        expansions += ["uitstel van betaling", "betalingsregeling", "betaaltermijn"]

    if any(k in low for k in ["toeslag", "toeslagen"]):
        expansions += ["huurtoeslag", "zorgtoeslag", "kinderopvangtoeslag", "kindgebonden budget", "toeslagpartner"]

    # Alleen extra termen toevoegen als ze nog niet in de query staan
    extras = [e for e in expansions if e.lower() not in low]
    return q if not extras else (q + " " + " ".join(extras))

async def run_genui_form_generate_flow(sid: str, inputs: Json) -> None:
    surface_id = "genui_form"
    query = str(inputs.get("query", "")).strip()
    if not query:
        return

    await _send_open_surface(sid, surface_id, "Generatieve UI — Formulier", _empty_surface_model("A2UI: Nieuwe run gestart…"))
    await _sleep_tick()

    await _set_form_state(sid, surface_id, _form_default_state())

    await _set_status(sid, surface_id, loading=True, message="A2UI: Formulier genereren…", step="start", source="", sourceReason="")
    await _set_results(sid, surface_id, [])
    await _sleep_tick()

    # 1) MCP citations
    await _set_status(sid, surface_id, loading=True, message="A2UI: Bronnen ophalen (MCP)…", step="bd_search")
    await _sleep_tick()

    q = _boost_query(query)
    search_resp = await _mcp_call_with_trace(sid, surface_id, "bd_search", {"query": q, "k": 5}, step="bd_search")
    citations = search_resp.get("items", []) if isinstance(search_resp, dict) else []
    citations_block: Json = {"kind": "citations", "title": "Bronnen (MCP)", "items": citations}

    # 2) A2A compose_form (deterministic)
    await _set_status(sid, surface_id, loading=True, message="A2UI: Formulier opstellen (A2A)…", step="compose_form")
    await _sleep_tick()

    try:
        resp = await _a2a_call_with_trace(sid, surface_id, a2a_genui_url, "compose_form", {"query": query, "citations": citations}, step="compose_form")
        data = _a2a_data_dict(resp)

        blocks_raw = data.get("blocks") or []
        if isinstance(blocks_raw, dict):
            blocks_raw = [blocks_raw]

        ui_source = str(data.get("ui_source") or "fallback")
        ui_reason = str(data.get("ui_source_reason") or "deterministic_form")

        blocks = _sanitize_genui_blocks(blocks_raw)

        merged: List[Json] = []
        if citations:
            merged.append(citations_block)
        merged.extend(blocks)

        form_block = _extract_first_form_block(blocks)
        await _set_form_state(sid, surface_id, {"query": query, "citations": citations, "form": form_block})

        await _set_status(sid, surface_id, source=str(ui_source), sourceReason=str(ui_reason))
        await _set_results(sid, surface_id, _sanitize_genui_blocks(merged))
        await _set_status(sid, surface_id, loading=False, message="A2UI: Klaar. Vul het formulier in en klik op Verstuur.", step="waiting")
    except Exception:
        await _set_status(sid, surface_id, source="fallback", sourceReason="a2a_down_or_error")

        form_block = {
            "kind": "form",
            "title": "Formulier (demo)",
            "formId": "contact_v1",
            "description": "Vul enkele gegevens in. Dit is een deterministische fallback.",
            "submitLabel": "Verstuur",
            "fields": [
                {"id": "email", "label": "E-mailadres", "type": "email", "required": True, "placeholder": "naam@example.nl"},
                {"id": "toelichting", "label": "Toelichting", "type": "textarea", "required": True, "placeholder": "Beschrijf kort uw vraag."},
            ],
        }

        merged: List[Json] = []
        if citations:
            merged.append(citations_block)
        merged.append({"kind": "notice", "title": "Formulier", "body": "A2A genui-agent niet bereikbaar; fallback actief."})
        merged.append(form_block)

        await _set_form_state(sid, surface_id, {"query": query, "citations": citations, "form": form_block})
        await _set_results(sid, surface_id, _sanitize_genui_blocks(merged))
        await _set_status(sid, surface_id, loading=False, message="A2UI: Klaar. (Form fallback)", step="waiting")


def _form_extend_fields(schema: List[Json], values: Dict[str, Any], query: str) -> List[Json]:
    """Deterministische (variant A) field extension op basis van ingevulde waarden.
    Bewust klein en voorspelbaar: dit is demo-UX (geen echt advies).
    """
    out: List[Json] = [f for f in schema if isinstance(f, dict)]
    ids = {str(f.get("id")) for f in out if isinstance(f, dict) and f.get("id")}

    def add_field(field: Json) -> None:
        fid = str(field.get("id") or "")
        if not fid or fid in ids:
            return
        out.append(field)
        ids.add(fid)

    qlow = (query or "").lower()

    kenmerk = str(values.get("kenmerk") or "").strip()
    if kenmerk and len(kenmerk) >= 6:
        add_field({"id": "dagtekening", "label": "Dagtekening (op brief/aanslag)", "type": "date", "required": False})

    bedrag_raw = values.get("bedrag")
    try:
        bedrag = float(bedrag_raw) if bedrag_raw not in (None, "") else 0.0
    except Exception:
        bedrag = 0.0

    if bedrag > 0:
        add_field({"id": "voorkeur", "label": "Waar gaat uw verzoek over?", "type": "select", "required": False,
                   "options": ["Uitstel aanvragen", "Betalingsregeling aanvragen", "Ik weet het niet"]})
        add_field({"id": "reden", "label": "Korte toelichting (waarom nu lastig betalen?)", "type": "textarea", "required": False,
                   "minLength": 15, "placeholder": "Bijv. tijdelijk minder inkomen of onverwachte kosten (demo)."})

    mot = str(values.get("motivering") or "").strip()
    vraag = str(values.get("vraag") or "").strip()
    if ("bezwaar" in qlow) or ("bezwaar" in (vraag.lower() if vraag else "")) or mot:
        add_field({"id": "route", "label": "Hoe wilt u het liefst indienen?", "type": "select", "required": False,
                   "options": ["Online", "Per post", "Weet ik niet"]})

    return out[:12]


async def run_genui_form_change_flow(sid: str, inputs: Json) -> None:
    """Variant A (deterministisch): voeg velden toe op basis van ingevulde waarden.
    Lichtgewicht: geen MCP/A2A calls, alleen model update.
    """
    surface_id = "genui_form"
    form_id = str(inputs.get("formId") or "").strip() or "form"
    values = inputs.get("values") or {}
    if not isinstance(values, dict):
        values = {}
    query = str(inputs.get("query") or "").strip()

    s = await hub.get(sid)
    if not s:
        return
    model = s.get_model(surface_id)
    form_state = model.get("form") if isinstance(model, dict) else None
    if not isinstance(form_state, dict):
        return

    form_block = form_state.get("form")
    if not isinstance(form_block, dict):
        return

    schema = form_block.get("fields") if isinstance(form_block.get("fields"), list) else []
    schema = [f for f in (schema or []) if isinstance(f, dict)]

    extended = _form_extend_fields(schema, values, query or str(form_state.get("query") or ""))

    base_ids = [str(f.get("id")) for f in schema if isinstance(f, dict)]
    ext_ids = [str(f.get("id")) for f in extended if isinstance(f, dict)]
    if ext_ids == base_ids:
        return

    updated_form = {**form_block, "fields": extended, "formId": form_id}

    await _set_form_state(
        sid,
        surface_id,
        {
            "query": query or str(form_state.get("query") or ""),
            "citations": form_state.get("citations") or [],
            "form": updated_form,
        },
    )

    results = model.get("results") if isinstance(model, dict) else None
    if not isinstance(results, list):
        return

    new_results: List[Json] = []
    replaced = False
    for b in results:
        if isinstance(b, dict) and b.get("kind") == "form" and not replaced:
            new_results.append(updated_form)
            replaced = True
        else:
            new_results.append(b)

    if not replaced:
        new_results.append(updated_form)

    await _set_results(sid, surface_id, _sanitize_genui_blocks(new_results))


async def run_genui_form_submit_flow(sid: str, inputs: Json) -> None:
    surface_id = "genui_form"
    form_id = str(inputs.get("formId") or "").strip() or "form"
    values = inputs.get("values") or {}
    if not isinstance(values, dict):
        values = {}
    query = str(inputs.get("query") or "").strip()

    ui_source = "fallback"
    ui_reason = "deterministic_form_explain"

    s = await hub.get(sid)
    if not s:
        return
    model = s.get_model(surface_id)
    form_state = model.get("form") if isinstance(model, dict) else None
    if not isinstance(form_state, dict):
        form_state = _form_default_state()

    citations = form_state.get("citations") or []
    form_block = form_state.get("form")
    if not isinstance(form_block, dict):
        form_block = None

    schema = []
    if form_block and isinstance(form_block.get("fields"), list):
        schema = form_block.get("fields") or []

    await _set_status(sid, surface_id, loading=True, message="A2UI: Validatie uitvoeren (MCP)…", step="validate_form", source=ui_source, sourceReason="deterministic_form")
    await _sleep_tick()

    validate_resp = await _mcp_call_with_trace(sid, surface_id, "validate_form", {"schema": schema, "values": values}, step="validate_form")
    ok = bool(validate_resp.get("ok")) if isinstance(validate_resp, dict) else False
    errors = validate_resp.get("errors") if isinstance(validate_resp, dict) else []
    if not isinstance(errors, list):
        errors = []

    if ok:
        notice = {"kind": "notice", "title": "Ingediend (demo)", "body": "Uw gegevens zijn ontvangen (demo). Hieronder ziet u de vervolgstappen."}
    else:
        lines = ["Controleer uw invoer:"]
        for e in errors[:8]:
            if isinstance(e, dict):
                fld = _safe_str(e.get("field") or "", max_len=40)
                msg = _safe_str(e.get("message") or "Ongeldige waarde", max_len=120)
                lines.append(f"- {fld}: {msg}")
        notice = {"kind": "notice", "title": "Controleer invoer", "body": "\n".join(lines)}

    await _set_status(sid, surface_id, loading=True, message="A2UI: Uitleg maken (A2A)…", step="explain_form", source=ui_source, sourceReason="deterministic_form")
    await _sleep_tick()

    explain_blocks: List[Json] = []
    try:
        resp = await _a2a_call_with_trace(sid, surface_id, a2a_genui, "explain_form", {"query": query, "ok": ok, "errors": errors, "values": values, "formId": form_id}, step="explain_form")
        data = _a2a_data_dict(resp)
        ui_source = str(data.get('ui_source') or ui_source)
        ui_reason = str(data.get('ui_source_reason') or ui_reason)
        blocks_raw = data.get('blocks') or []
        if isinstance(blocks_raw, dict):
            blocks_raw = [blocks_raw]
        explain_blocks = _sanitize_genui_blocks(blocks_raw)
    except Exception:
        explain_blocks = [
            {"kind": "callout", "title": "Vervolgstap (demo)", "body": "Ga verder met het verzamelen van relevante stukken en controleer de termijnen. (Deterministische fallback.)"}
        ]



    merged: List[Json] = []
    if citations:
        merged.append({"kind": "citations", "title": "Bronnen (MCP)", "items": citations})
    merged.append(notice)
    if form_block:
        merged.append(form_block)
    merged.extend(explain_blocks)

    await _set_form_state(sid, surface_id, {"query": query or form_state.get("query") or "", "citations": citations, "form": form_block})
    await _set_results(sid, surface_id, _sanitize_genui_blocks(merged))

    await _set_status(
        sid,
        surface_id,
        loading=False,
        message=("A2UI: Klaar. (Formulier ingediend)" if ok else "A2UI: Klaar. Corrigeer de velden en verstuur opnieuw."),
        step="done",
        source=ui_source,
        sourceReason=ui_reason,
    )
