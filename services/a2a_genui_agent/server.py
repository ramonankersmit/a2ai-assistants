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

# Keep it deterministic and avoid long rambles
GEMINI_MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "900"))
TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.0"))

log = logging.getLogger("a2a_genui_agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = FastAPI(title="A2A GenUI Agent (Demo)", version="0.1.6")

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

_ALLOWED_KINDS = {"callout", "citations", "accordion", "next_questions", "notice"}


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
        "version": "0.1.6",
    }


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
        "Je maakt UI-blokken voor een agent-gedreven interface (A2UI).\n"
        "Return EXACTLY één JSON object en niets anders.\n"
        "Geen markdown, geen uitleg, geen code fences.\n\n"
        "Toegestane kinds: callout, citations, accordion, next_questions, notice.\n"
        "Gebruik exact deze keys:\n"
        "- callout: {kind,title,body}\n"
        "- citations: {kind,title,items:[{title,url,snippet}]}\n"
        "- accordion: {kind,title,items:[{q,a}]}\n"
        "- next_questions: {kind,title,items:[string]}\n"
        "- notice: {kind,title,body}\n\n"
        "Regels:\n"
        "- Nederlands (B1/B2)\n"
        "- Geen persoonsgegevens\n        "
        "- citations-blok gebruikt exact de meegegeven citations (niet verzinnen)\n"
        "- Minimaal 4 blokken, maximaal 6\n"
        "- Callout max 6 regels\n"
        "- Accordion 2-4 Q/A\n"
        "- Next_questions 3-5 items\n"
    )


def _cleanup_json_like(s: str) -> str:
    # Replace “smart quotes”
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    # Remove trailing commas before } or ]
    s = re.sub(r",\s*([}\]])", r"\1", s)
    # Strip code fences
    s = re.sub(r"^```(?:json)?\s*", "", s.strip())
    s = re.sub(r"\s*```$", "", s)
    return s


def _extract_json(text: str) -> Optional[Json]:
    if not text:
        return None
    s = _cleanup_json_like(text)

    # Try whole string
    try:
        return json.loads(s)
    except Exception:
        pass

    # Try substring between first { and last }
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = _cleanup_json_like(s[start : end + 1])
        try:
            return json.loads(candidate)
        except Exception:
            return None
    return None


def _shape_blocks(obj: Json, citations: List[Json]) -> Optional[List[Json]]:
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

        title = str(b.get("title") or "").strip() or {
            "callout": "Kern",
            "citations": "Bronnen",
            "accordion": "Veelgestelde vragen",
            "next_questions": "Vervolgvraag",
            "notice": "Let op",
        }.get(kind, "Blok")

        if kind == "citations":
            out.append({"kind": "citations", "title": title, "items": citations})
            continue

        if kind in ("callout", "notice"):
            # accept alternate key "text"
            body = str(b.get("body") or b.get("text") or "").strip()
            out.append({"kind": kind, "title": title, "body": body})
            continue

        if kind == "accordion":
            items = b.get("items") if isinstance(b.get("items"), list) else []
            shaped = []
            for it in items[:4]:
                if isinstance(it, dict):
                    # accept alternate keys question/answer
                    q = str(it.get("q") or it.get("question") or "").strip()
                    a = str(it.get("a") or it.get("answer") or "").strip()
                    if q and a:
                        shaped.append({"q": q, "a": a})
            if len(shaped) >= 2:
                out.append({"kind": "accordion", "title": title, "items": shaped})
            continue

        if kind == "next_questions":
            items = b.get("items") if isinstance(b.get("items"), list) else []
            shaped = [str(x).strip() for x in items if str(x).strip()][:5]
            if len(shaped) >= 3:
                out.append({"kind": "next_questions", "title": title, "items": shaped})
            continue

    if not any(x.get("kind") == "citations" for x in out):
        out.insert(0, {"kind": "citations", "title": "Bronnen", "items": citations})

    if len(out) < 4:
        return None
    return out[:6]


async def _gemini_generate(prompt_text: str) -> Tuple[Optional[str], str]:
    if not GEMINI_API_KEY:
        return None, "no_api_key"

    url = f"{GEMINI_BASE_URL}/{GEMINI_API_VERSION}/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

    # Key point: responseMimeType nudges JSON-only without schema (avoids 400)
    body = {
        "systemInstruction": {"parts": [{"text": _system_instruction()}]},
        "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": TEMPERATURE,
            "maxOutputTokens": GEMINI_MAX_TOKENS,
            "candidateCount": 1,
            "responseMimeType": "application/json",
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=body)
            if r.status_code != 200:
                log.warning("Gemini HTTP %s body=%r", r.status_code, r.text[:800])
                return None, f"http_{r.status_code}"

            data = r.json()
            cand0 = (data.get("candidates") or [{}])[0]
            parts = ((cand0.get("content") or {}).get("parts") or [])
            texts = [p.get("text", "") for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)]
            text = "\n".join(texts).strip()
            return text or None, "ok"
    except httpx.ConnectError:
        return None, "connect_error"
    except httpx.ReadTimeout:
        return None, "timeout"
    except Exception:
        return None, "exception"


async def _gemini_repair_to_json(bad_output: str, citations: List[Json]) -> Tuple[Optional[Json], str]:
    # Give an explicit template to fill
    template = {
        "blocks": [
            {"kind": "callout", "title": "Kern", "body": ""},
            {"kind": "citations", "title": "Bronnen", "items": citations},
            {"kind": "accordion", "title": "Veelgestelde vragen", "items": [{"q": "", "a": ""}, {"q": "", "a": ""}]},
            {"kind": "next_questions", "title": "Vervolgvraag", "items": ["", "", ""]},
            {"kind": "notice", "title": "Let op", "body": ""},
        ]
    }

    repair_prompt = (
        "Converteer de onderstaande output naar EXACT één valide JSON object dat exact het TEMPLATE volgt.\n"
        "Return ONLY JSON.\n\n"
        "TEMPLATE:\n"
        + json.dumps(template, ensure_ascii=False)
        + "\n\nOUTPUT:\n"
        + (bad_output or "")
    )

    text, reason = await _gemini_generate(repair_prompt)
    if not text or reason != "ok":
        return None, f"repair_{reason}"

    obj = _extract_json(text)
    if isinstance(obj, dict):
        return obj, "ok"
    return None, "repair_bad_json"


async def _gemini_compose(query: str, citations: List[Json]) -> Tuple[Optional[List[Json]], str]:
    payload = {"query": query, "citations": citations}

    # Provide a small template example to reduce variance
    example = {
        "blocks": [
            {"kind": "callout", "title": "Kern", "body": "Korte kern (max 6 regels)."},
            {"kind": "citations", "title": "Bronnen", "items": citations},
            {"kind": "accordion", "title": "Veelgestelde vragen", "items": [{"q": "Vraag?", "a": "Antwoord."}, {"q": "Vraag?", "a": "Antwoord."}]},
            {"kind": "next_questions", "title": "Vervolgvraag", "items": ["Vraag 1", "Vraag 2", "Vraag 3"]},
        ]
    }

    prompt = (
        "Maak UI-blokken (A2UI) op basis van de vraag en de bronnen.\n"
        "Return ONLY JSON.\n\n"
        "Voorbeeldvorm (gebruik dezelfde keys):\n"
        + json.dumps(example, ensure_ascii=False)
        + "\n\nInput:\n"
        + json.dumps(payload, ensure_ascii=False)
    )

    text, reason = await _gemini_generate(prompt)
    if not text or reason != "ok":
        return None, reason

    obj = _extract_json(text)
    if isinstance(obj, dict):
        blocks = _shape_blocks(obj, citations)
        if blocks:
            return blocks, "ok"

    log.warning("Gemini bad_json; attempting repair. head=%r tail=%r", (text or "")[:200], (text or "")[-200:])
    repaired, r_reason = await _gemini_repair_to_json(text or "", citations)
    if isinstance(repaired, dict):
        blocks2 = _shape_blocks(repaired, citations)
        if blocks2:
            return blocks2, "ok"

    return None, "bad_json"


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
