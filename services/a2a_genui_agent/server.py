from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

Json = Dict[str, Any]

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
GEMINI_API_VERSION = os.getenv("GEMINI_API_VERSION", "v1beta").strip()
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/")

GEMINI_MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "900"))
TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.4"))

log = logging.getLogger("a2a_genui_agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Avoid leaking key in httpx logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = FastAPI(title="A2A GenUI Agent (Demo)", version="0.1.0")

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


@app.on_event("startup")
async def _startup():
    if GEMINI_API_KEY:
        log.info("Gemini enabled for GenUI (model=%s version=%s)", GEMINI_MODEL, GEMINI_API_VERSION)
    else:
        log.info("Gemini disabled for GenUI (no GEMINI_API_KEY) — deterministic fallback")


@app.get("/.well-known/agent-card.json")
async def agent_card():
    return {
        "name": "genui-agent",
        "description": "Composes UI blocks (A2UI-friendly) from search results (Gemini or fallback).",
        "url": "http://localhost:8030/",
        "capabilities": ["compose_ui"],
        "protocol": "a2a-jsonrpc",
        "version": "0.1.0",
    }


_ALLOWED_KINDS = {"callout", "citations", "accordion", "next_questions", "notice"}


def _fallback_blocks(query: str, citations: List[Json]) -> List[Json]:
    top = citations[0] if citations else {}
    top_title = str(top.get("title", ""))
    top_snip = str(top.get("snippet", ""))

    faq = [
        {"q": "Wat laat deze tegel zien?", "a": "De UI wordt opgebouwd uit blokken op basis van data (A2UI). In stap 1.3 kiest de LLM de blokken."},
        {"q": "Waarom niet direct HTML genereren?", "a": "Veiligheid/consistentie: alleen whitelisted blokken worden gerenderd in Belastingdienst-stijl."},
    ]
    next_q = ["Hoe maak ik bezwaar?", "Ik kan niet op tijd betalen — betalingsregeling?", "Kan ik huurtoeslag krijgen?"]

    return [
        {
            "kind": "callout",
            "title": "Kern (fallback)",
            "body": (
                f"Vraag: {query}\n\n"
                + (f"Top-bron: {top_title}\n{top_snip}\n\n" if top_title else "")
                + "Dit is een deterministische fallback. Met Gemini kan de agent dynamisch kiezen welke blokken het meest relevant zijn."
            ),
        },
        {"kind": "citations", "title": "Bronnen", "items": citations},
        {"kind": "accordion", "title": "Veelgestelde vragen (demo)", "items": faq},
        {"kind": "next_questions", "title": "Vervolgvraag", "items": next_q},
        {"kind": "notice", "title": "Let op", "body": "Dit is demo-informatie. Raadpleeg officiële pagina’s voor actuele details."},
    ]


def _system_instruction() -> str:
    return (
        "Je maakt UI-blokken voor een agent-gedreven interface (A2UI). "
        "Je output is STRICT JSON, zonder markdown, zonder extra tekst.\n\n"
        "Je mag uitsluitend deze kinds gebruiken: callout, citations, accordion, next_questions, notice.\n"
        "JSON schema (vereist):\n"
        "{\n"
        '  "blocks": [\n'
        '    {"kind":"callout", "title":str, "body":str},\n'
        '    {"kind":"citations", "title":str, "items":[{"title":str,"url":str,"snippet":str}]},\n'
        '    {"kind":"accordion", "title":str, "items":[{"q":str,"a":str}]},\n'
        '    {"kind":"next_questions", "title":str, "items":[str,...]},\n'
        '    {"kind":"notice", "title":str, "body":str}\n'
        "  ]\n"
        "}\n\n"
        "Regels:\n"
        "- Schrijf in het Nederlands, B1/B2.\n"
        "- Geen persoonsgegevens.\n"
        "- Gebruik exact de meegegeven citations in het citations-blok (niet verzinnen, niet aanpassen).\n"
        "- Minimaal 4 blokken.\n"
        "- Callout moet een korte kern geven (max 6 regels).\n"
        "- Accordion: 2-4 Q/A items.\n"
        "- Next_questions: 3-5 korte vervolgvragen."
    )


def _extract_json(text: str) -> Optional[Json]:
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)

    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", s)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None


def _validate_blocks(obj: Json, citations: List[Json]) -> Optional[List[Json]]:
    blocks = obj.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return None

    out: List[Json] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        kind = b.get("kind")
        if kind not in _ALLOWED_KINDS:
            continue

        if kind == "citations":
            out.append({"kind": "citations", "title": b.get("title") or "Bronnen", "items": citations})
            continue

        if kind == "callout":
            out.append({"kind": "callout", "title": b.get("title") or "Kern", "body": str(b.get("body") or "")})
            continue

        if kind == "notice":
            out.append({"kind": "notice", "title": b.get("title") or "Let op", "body": str(b.get("body") or "")})
            continue

        if kind == "accordion":
            items = b.get("items") if isinstance(b.get("items"), list) else []
            shaped = []
            for it in items[:4]:
                if isinstance(it, dict):
                    shaped.append({"q": str(it.get("q") or ""), "a": str(it.get("a") or "")})
            out.append({"kind": "accordion", "title": b.get("title") or "Veelgestelde vragen", "items": shaped})
            continue

        if kind == "next_questions":
            items = b.get("items") if isinstance(b.get("items"), list) else []
            shaped = [str(x) for x in items[:5] if str(x).strip()]
            out.append({"kind": "next_questions", "title": b.get("title") or "Vervolgvraag", "items": shaped})
            continue

    if not any(b.get("kind") == "citations" for b in out):
        out.append({"kind": "citations", "title": "Bronnen", "items": citations})

    if len(out) < 4:
        return None

    return out


async def _gemini_compose(query: str, citations: List[Json]) -> Tuple[Optional[List[Json]], str]:
    if not GEMINI_API_KEY:
        return None, "no_api_key"

    url = f"{GEMINI_BASE_URL}/{GEMINI_API_VERSION}/models/{GEMINI_MODEL}:generateContent"
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}

    user_payload = {"query": query, "citations": citations}

    body = {
        "systemInstruction": {"parts": [{"text": _system_instruction()}]},
        "contents": [
            {"role": "user", "parts": [{"text": "Maak UI-blokken voor deze vraag en bronnen. Input JSON:\n" + json.dumps(user_payload, ensure_ascii=False)}]}
        ],
        "generationConfig": {"temperature": TEMPERATURE, "maxOutputTokens": GEMINI_MAX_TOKENS, "candidateCount": 1},
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, headers=headers, json=body)
            if r.status_code != 200:
                return None, f"http_{r.status_code}"

            data = r.json()
            cand0 = (data.get("candidates") or [{}])[0]
            parts = ((cand0.get("content") or {}).get("parts") or [])
            text = ""
            if isinstance(parts, list):
                text = "\n".join([p.get("text", "") for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)]).strip()

            obj = _extract_json(text)
            if not isinstance(obj, dict):
                return None, "bad_json"

            blocks = _validate_blocks(obj, citations)
            if not blocks:
                return None, "invalid_blocks"

            return blocks, "ok"
    except httpx.ConnectError:
        return None, "connect_error"
    except httpx.ReadTimeout:
        return None, "timeout"
    except Exception:
        return None, "exception"


@app.post("/")
async def jsonrpc(payload: Json = Body(...)):
    if payload.get("jsonrpc") != "2.0":
        raise HTTPException(400, "Invalid JSON-RPC")

    method = payload.get("method")
    req_id = payload.get("id")
    if method != "message/send":
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}

    params = payload.get("params") or {}
    capability = params.get("capability")
    if capability != "compose_ui":
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Unknown capability"}}

    message = (params.get("message") or {})
    parts = message.get("parts") or []
    data_part = parts[0] if parts else {}
    data = data_part.get("data") or {}

    query = str(data.get("query") or "").strip()
    citations = data.get("citations") or []
    if not isinstance(citations, list):
        citations = []

    blocks, reason = await _gemini_compose(query, citations)
    if blocks:
        result = {"blocks": blocks, "ui_source": "gemini", "ui_source_reason": reason}
    else:
        result = {"blocks": _fallback_blocks(query, citations), "ui_source": "fallback", "ui_source_reason": reason}

    log.info("ui_source=%s reason=%s", result.get("ui_source"), result.get("ui_source_reason"))
    return {"jsonrpc": "2.0", "id": req_id, "result": {"status": "ok", "data": result}}
