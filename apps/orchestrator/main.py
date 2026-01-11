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


# In-memory demo state (per session). Kept intentionally small and deterministic.
_GENUI_TREE_STATE: Dict[str, Dict[str, Any]] = {}
_GENUI_FORM_STATE: Dict[str, Dict[str, Any]] = {}

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

GENUI_ALLOWED_KINDS = {"accordion", "callout", "citations", "decision", "form", "next_questions", "notice"}


def _safe_str(value: Any, *, max_len: int = 4000) -> str:
    s = "" if value is None else str(value)
    s = s.strip()
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s




def _tree_start_blocks() -> List[Json]:
    return [
        {
            "kind": "decision",
            "title": "Stap 1",
            "question": "Waar gaat uw vraag over?",
            "options": ["Bezwaar maken", "Betalen/uitstel", "Toeslagen"],
        }
    ]

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


def _sanitize_genui_blocks(blocks: Any, *, max_blocks: int = 12) -> List[Json]:
    """Accept only known block kinds and coerce fields to a safe shape.

    Notes:
    - Accepts either a list of blocks or a single block dict.
    - Drops unknown kinds and overlong content defensively (demo stability).
    """
    if isinstance(blocks, dict):
        blocks = [blocks]
    if not isinstance(blocks, list):
        return []

    def _sanitize_option(opt: Any) -> Any:
        # Allow either string options or {label,value} objects.
        if isinstance(opt, str):
            return _safe_str(opt, max_len=140)
        if isinstance(opt, dict):
            label = _safe_str(opt.get("label") or opt.get("title") or opt.get("value") or opt.get("id") or "", max_len=140)
            value = opt.get("value") if opt.get("value") is not None else opt.get("id")
            value = _safe_str(value or label, max_len=140)
            return {"label": label, "value": value}
        return None

    def _sanitize_field(f: Any) -> Optional[Json]:
        if not isinstance(f, dict):
            return None
        fid = _safe_str(f.get("id") or "", max_len=40)
        if not fid:
            return None
        label = _safe_str(f.get("label") or fid, max_len=120)
        ftype = _safe_str(f.get("type") or "text", max_len=20).lower()
        allowed_types = {"text", "email", "number", "date", "textarea", "select"}
        if ftype not in allowed_types:
            ftype = "text"

        out: Json = {
            "id": fid,
            "label": label,
            "type": ftype,
            "required": bool(f.get("required")),
        }

        # Optional UX hints / constraints
        if f.get("placeholder") is not None:
            out["placeholder"] = _safe_str(f.get("placeholder"), max_len=140)

        if f.get("minLength") is not None:
            try:
                out["minLength"] = int(f.get("minLength"))
            except Exception:
                pass
        if f.get("maxLength") is not None:
            try:
                out["maxLength"] = int(f.get("maxLength"))
            except Exception:
                pass
        if f.get("pattern") is not None:
            out["pattern"] = _safe_str(f.get("pattern"), max_len=140)

        if ftype == "select":
            raw_opts = f.get("options") or []
            if isinstance(raw_opts, list):
                opts: List[str] = []
                for o in raw_opts[:12]:
                    if isinstance(o, str):
                        opts.append(_safe_str(o, max_len=140))
                    elif isinstance(o, dict):
                        # allow {label:...} too, but store as strings for selects
                        lbl = _safe_str(o.get("label") or o.get("value") or o.get("id") or "", max_len=140)
                        if lbl:
                            opts.append(lbl)
                out["options"] = opts
        return out

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
                    "body": _safe_str(b.get("body") or "", max_len=2000),
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

        if kind == "notice":
            out.append(
                {
                    "kind": "notice",
                    "title": _safe_str(b.get("title") or "Let op", max_len=140),
                    "body": _safe_str(b.get("body") or "", max_len=2000),
                }
            )
            continue

        if kind == "decision":
            q = _safe_str(b.get("question") or b.get("title") or "Kies een optie", max_len=180)
            help_txt = _safe_str(b.get("help") or "", max_len=280)
            raw_opts = b.get("options") or []
            opts: List[Any] = []
            if isinstance(raw_opts, list):
                for o in raw_opts[:12]:
                    so = _sanitize_option(o)
                    if so is not None and so != "":
                        opts.append(so)
            out.append({"kind": "decision", "question": q, "help": help_txt, "options": opts})
            continue

        if kind == "form":
            title = _safe_str(b.get("title") or "Gegevens", max_len=140)
            form_id = _safe_str(b.get("formId") or b.get("form_id") or b.get("id") or "form", max_len=40)
            submit = _safe_str(b.get("submitLabel") or b.get("submit_label") or "Verstuur", max_len=40)

            raw_fields = b.get("fields") or []
            fields: List[Json] = []
            if isinstance(raw_fields, list):
                for f in raw_fields[:12]:
                    sf = _sanitize_field(f)
                    if sf:
                        fields.append(sf)

            out.append({"kind": "form", "title": title, "formId": form_id, "fields": fields, "submitLabel": submit})
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
        elif target == "genui_tree":
            await _send_open_surface(sid, "genui_tree", "Generatieve UI — Wizard", _empty_surface_model("A2UI: Klik op Opnieuw starten."))
            asyncio.create_task(run_genui_tree_start_flow(sid))
        elif target == "genui_form":
            await _send_open_surface(sid, "genui_form", "Generatieve UI — Formulier", _empty_surface_model("A2UI: Typ een vraag en klik op Genereer formulier."))
        else:
            await _send_open_surface(sid, "home", "Belastingdienst Assistants", _home_surface_model())
        return {"ok": True}

    if name == "toeslagen/check":
        asyncio.create_task(run_toeslagen_flow(sid, data))
        return {"ok": True}

    if name == "toeslagen/reset":
        # Reset surface state (inputs are reset client-side; we reset status/results server-side)
        await _send_open_surface(
            sid,
            "toeslagen",
            "Toeslagen Check",
            _empty_surface_model("A2UI: Vul de gegevens in en klik op Check."),
        )
        return {"ok": True}

    if name == "bezwaar/analyse":
        asyncio.create_task(run_bezwaar_flow(sid, data))
        return {"ok": True}

    if name == "genui/search":
        asyncio.create_task(run_genui_search_flow(sid, data))
        return {"ok": True}


    if name == "genui_tree/start":
        asyncio.create_task(run_genui_tree_start_flow(sid))
        return {"ok": True}

    if name == "genui_tree/choose":
        asyncio.create_task(run_genui_tree_choose_flow(sid, data))
        return {"ok": True}

    if name == "genui_form/generate":
        asyncio.create_task(run_genui_form_generate_flow(sid, data))
        return {"ok": True}

    # Backward compatible aliases (older UI builds)
    if name == "genui/form_generate":
        asyncio.create_task(run_genui_form_generate_flow(sid, data))
        return {"ok": True}

    if name == "genui_form/change":
        asyncio.create_task(run_genui_form_change_flow(sid, data))
        return {"ok": True}

    # Backward compatible aliases (older UI builds)
    if name == "genui/form_change":
        asyncio.create_task(run_genui_form_change_flow(sid, data))
        return {"ok": True}

    if name == "genui_form/submit":
        asyncio.create_task(run_genui_form_submit_flow(sid, data))
        return {"ok": True}

    # Backward compatible aliases (older UI builds)
    if name == "genui/form_submit":
        asyncio.create_task(run_genui_form_submit_flow(sid, data))
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



def _validate_form_values(fields: List[Json], values: Dict[str, Any]) -> Tuple[bool, List[Json]]:
    errors: List[Json] = []
    for f in fields:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id") or "").strip()
        if not fid:
            continue
        label = str(f.get("label") or fid)
        required = bool(f.get("required", False))
        ftype = str(f.get("type") or "text")
        v = values.get(fid)

        s = "" if v is None else str(v).strip()
        if required and not s:
            errors.append({"field": fid, "message": f"{label} is verplicht."})
            continue

        if not s:
            continue

        min_len = f.get("minLength")
        max_len = f.get("maxLength")
        try:
            if min_len is not None and len(s) < int(min_len):
                errors.append({"field": fid, "message": f"{label} is te kort (min. {int(min_len)} tekens)."})
        except Exception:
            pass
        try:
            if max_len is not None and len(s) > int(max_len):
                errors.append({"field": fid, "message": f"{label} is te lang (max. {int(max_len)} tekens)."})
        except Exception:
            pass

        if ftype == "email" and s and ("@" not in s or "." not in s.split("@")[-1]):
            errors.append({"field": fid, "message": f"{label} lijkt geen geldig e-mailadres."})

    return (len(errors) == 0), errors


def _extend_form_fields(fields: List[Json], values: Dict[str, Any], query: str) -> List[Json]:
    out: List[Json] = [f for f in fields if isinstance(f, dict)]
    ids = {str(f.get("id")) for f in out if isinstance(f, dict) and f.get("id")}

    def add(field: Json) -> None:
        fid = str(field.get("id") or "").strip()
        if not fid or fid in ids:
            return
        out.append(field)
        ids.add(fid)

    qlow = (query or "").lower()
    kenmerk = str(values.get("kenmerk") or "").strip()
    if kenmerk and len(kenmerk) >= 6:
        add({"id": "dagtekening", "label": "Dagtekening (op brief/aanslag)", "type": "date", "required": False})

    bedrag_raw = values.get("bedrag")
    try:
        bedrag = float(bedrag_raw) if bedrag_raw not in (None, "") else 0.0
    except Exception:
        bedrag = 0.0

    if bedrag > 0:
        add({"id": "voorkeur", "label": "Waar gaat uw verzoek over?", "type": "select", "required": False, "options": ["Uitstel aanvragen", "Betalingsregeling aanvragen", "Ik weet het niet"]})
        add({"id": "reden", "label": "Korte toelichting (waarom nu lastig betalen?)", "type": "textarea", "required": False, "minLength": 15})

    if "bezwaar" in qlow or str(values.get("motivering") or "").strip():
        add({"id": "route", "label": "Hoe wilt u het liefst indienen?", "type": "select", "required": False, "options": ["Online", "Per post", "Weet ik niet"]})

    return out[:14]

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


async def run_genui_tree_start_flow(sid: str) -> None:
    surface_id = "genui_tree"
    _GENUI_TREE_STATE[sid] = {"node": "root", "path": []}

    await _send_open_surface(sid, surface_id, "Generatieve UI — Wizard", _empty_surface_model("A2UI: Nieuwe wizard gestart…"))
    await _sleep_tick()

    await _set_status(
        sid,
        surface_id,
        loading=False,
        message="A2UI: Kies een onderwerp om te beginnen.",
        step="start",
        source="fallback",
        sourceReason="deterministic_tree",
    )
    await _set_results(sid, surface_id, _tree_start_blocks())


async def run_genui_tree_choose_flow(sid: str, inputs: Json) -> None:
    surface_id = "genui_tree"
    option = str(inputs.get("option") or inputs.get("choice") or "").strip()
    if not option:
        return

    state = _GENUI_TREE_STATE.get(sid) or {"node": "root", "path": []}
    await _set_status(
        sid,
        surface_id,
        loading=True,
        message="A2UI: Volgende stap bepalen (A2A)…",
        step="next_node",
        source="fallback",
        sourceReason="deterministic_tree",
    )
    await _sleep_tick()

    try:
        data = await _a2a_call_with_trace(
            sid,
            surface_id,
            a2a_genui,
            "next_node",
            {"state": state, "choice": option},
            step="next_node",
        )
        if not isinstance(data, dict):
            data = {}
        blocks_raw = data.get("blocks") or []
        if isinstance(blocks_raw, dict):
            blocks_raw = [blocks_raw]
        blocks = _sanitize_genui_blocks(blocks_raw)

        new_state = data.get("tree") if isinstance(data.get("tree"), dict) else None
        if new_state:
            _GENUI_TREE_STATE[sid] = new_state

        ui_source = _safe_str(data.get("ui_source", "fallback"), max_len=40).lower() or "fallback"
        ui_reason = _safe_str(data.get("ui_source_reason", "deterministic_tree"), max_len=80) or "deterministic_tree"

        await _set_status(sid, surface_id, loading=False, message="A2UI: Klaar. (Wizard)", step="done", source=ui_source, sourceReason=ui_reason)
        await _set_results(sid, surface_id, blocks)
    except Exception:
        await _set_status(sid, surface_id, loading=False, message="A2UI: Klaar. (Wizard fallback)", step="done", source="fallback", sourceReason="a2a_down_or_error")
        await _set_results(sid, surface_id, _tree_start_blocks())


async def run_genui_form_generate_flow(sid: str, inputs: Json) -> None:
    surface_id = "genui_form"
    query = str(inputs.get("query") or "").strip()
    if not query:
        return

    await _send_open_surface(sid, surface_id, "Generatieve UI — Formulier", _empty_surface_model("A2UI: Formulier genereren…"))
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: Bronnen ophalen (MCP)…", step="bd_search", source="", sourceReason="")
    await _set_results(sid, surface_id, [])
    await _sleep_tick()

    search_resp = await _mcp_call_with_trace(sid, surface_id, "bd_search", {"query": query, "k": 5}, step="bd_search")
    citations = search_resp.get("items", []) if isinstance(search_resp, dict) else []
    citations_block: Json = {"kind": "citations", "title": "Bronnen (MCP)", "items": citations}

    await _set_results(sid, surface_id, [citations_block])
    await _sleep_tick()

    await _set_status(sid, surface_id, loading=True, message="A2UI: Formulier opbouwen (A2A)…", step="compose_form")
    await _sleep_tick()

    ui_source = "fallback"
    ui_reason = "deterministic_form"
    blocks: List[Json] = []
    form_block: Optional[Json] = None

    try:
        data = await _a2a_call_with_trace(sid, surface_id, a2a_genui, "compose_form", {"query": query, "citations": citations}, step="compose_form")
        if not isinstance(data, dict):
            data = {}
        blocks_raw = data.get("blocks") or []
        if isinstance(blocks_raw, dict):
            blocks_raw = [blocks_raw]
        blocks = _sanitize_genui_blocks(blocks_raw)
        blocks = [b for b in blocks if b.get("kind") != "citations"]

        ui_source = _safe_str(data.get("ui_source", "fallback"), max_len=40).lower() or "fallback"
        ui_reason = _safe_str(data.get("ui_source_reason", "deterministic_form"), max_len=80) or "deterministic_form"
    except Exception:
        blocks = [{"kind": "notice", "title": "Formulier", "body": "GenUI-agent niet bereikbaar; fallback actief."}]
        ui_source = "fallback"
        ui_reason = "a2a_down_or_error"

    for b in blocks:
        if isinstance(b, dict) and b.get("kind") == "form":
            form_block = b
            break

    _GENUI_FORM_STATE[sid] = {"query": query, "citations": citations, "form": form_block}

    merged: List[Json] = [citations_block]
    merged.extend(blocks)

    await _set_status(sid, surface_id, loading=False, message="A2UI: Klaar. (Formulier)", step="done", source=ui_source, sourceReason=ui_reason)
    await _set_results(sid, surface_id, merged)


async def run_genui_form_change_flow(sid: str, inputs: Json) -> None:
    surface_id = "genui_form"
    values = inputs.get("values") or {}
    if not isinstance(values, dict):
        values = {}
    query = str(inputs.get("query") or "").strip()

    state = _GENUI_FORM_STATE.get(sid) or {}
    form_block = state.get("form")
    if not isinstance(form_block, dict):
        return

    fields = form_block.get("fields") if isinstance(form_block.get("fields"), list) else []
    fields = [f for f in fields if isinstance(f, dict)]

    extended = _extend_form_fields(fields, values, query or str(state.get("query") or ""))
    base_ids = [str(f.get("id")) for f in fields]
    ext_ids = [str(f.get("id")) for f in extended]
    if base_ids == ext_ids:
        return

    updated_form = {**form_block, "fields": extended}
    state["form"] = updated_form
    state["query"] = query or str(state.get("query") or "")
    _GENUI_FORM_STATE[sid] = state

    s = await hub.get(sid)
    if not s:
        return
    model = s.get_model(surface_id)
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

    await _set_status(sid, surface_id, loading=False, message="A2UI: Formulier aangevuld.", step="change", source="fallback", sourceReason="deterministic_form_extend")
    await _set_results(sid, surface_id, _sanitize_genui_blocks(new_results))


async def run_genui_form_submit_flow(sid: str, inputs: Json) -> None:
    surface_id = "genui_form"
    values = inputs.get("values") or {}
    if not isinstance(values, dict):
        values = {}

    state = _GENUI_FORM_STATE.get(sid) or {}
    query = str(state.get("query") or inputs.get("query") or "").strip()
    form_block = state.get("form")
    fields = form_block.get("fields") if isinstance(form_block, dict) and isinstance(form_block.get("fields"), list) else []
    fields = [f for f in fields if isinstance(f, dict)]

    await _set_status(sid, surface_id, loading=True, message="A2UI: Formulier controleren…", step="validate", source="fallback", sourceReason="deterministic_form")
    await _sleep_tick()

    ok, errors = _validate_form_values(fields, values)

    await _set_status(sid, surface_id, loading=True, message="A2UI: Vervolgstappen opstellen (A2A)…", step="explain_form", source="fallback", sourceReason="deterministic_form_explain")
    await _sleep_tick()

    explain_blocks: List[Json] = []
    try:
        data = await _a2a_call_with_trace(sid, surface_id, a2a_genui, "explain_form", {"query": query, "ok": ok, "errors": errors}, step="explain_form")
        if not isinstance(data, dict):
            data = {}
        blocks_raw = data.get("blocks") or []
        if isinstance(blocks_raw, dict):
            blocks_raw = [blocks_raw]
        explain_blocks = _sanitize_genui_blocks(blocks_raw)
    except Exception:
        if ok:
            explain_blocks = [
                {"kind": "notice", "title": "Ingediend (demo)", "body": "Uw gegevens zijn ontvangen (demo). Hieronder ziet u de vervolgstappen."},
                {"kind": "callout", "title": "Vervolgstappen (demo)", "body": "1) Bewaar uw kenmerk/nummer.\n2) Verzamel relevante documenten.\n3) Let op termijnen."},
                {"kind": "next_questions", "title": "Vervolgvraag", "items": ["Hoe maak ik bezwaar?", "Hoe vraag ik uitstel aan?", "Wat heb ik nodig?"]},
            ]
        else:
            explain_blocks = [{"kind": "notice", "title": "Niet verstuurd", "body": "Controleer de velden en probeer opnieuw."}]

    s = await hub.get(sid)
    model = s.get_model(surface_id) if s else None
    results = model.get("results") if isinstance(model, dict) else []
    if not isinstance(results, list):
        results = []

    merged: List[Json] = []
    for b in results:
        if isinstance(b, dict) and b.get("kind") == "citations":
            merged.append(b)
            break
    if isinstance(state.get("form"), dict):
        merged.append(state["form"])
    merged.extend(explain_blocks)

    await _set_results(sid, surface_id, _sanitize_genui_blocks(merged))
    await _set_status(sid, surface_id, loading=False, message=("A2UI: Klaar. (Formulier ingediend)" if ok else "A2UI: Klaar. Corrigeer de velden en verstuur opnieuw."), step="done", source="fallback", sourceReason="deterministic_form_explain")

