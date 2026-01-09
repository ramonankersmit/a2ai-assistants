from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

Json = Dict[str, Any]
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

app = FastAPI(title="A2A Bezwaar Agent (Demo)", version="0.1.0")

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


@app.get("/.well-known/agent-card.json")
async def agent_card():
    return {
        "name": "bezwaar-agent",
        "description": "Structureert bezwaarbrieven en genereert conceptreactie (Gemini of fallback) (demo).",
        "url": "http://localhost:8020/",
        "capabilities": ["structure_bezwaar"],
        "protocol": "a2a-jsonrpc",
    }


def _deterministic_draft(overview: Json) -> str:
    return (
        "Geachte heer/mevrouw,\n\n"
        "Wij hebben uw bezwaar ontvangen. Op basis van de beschikbare gegevens beoordelen wij uw verzoek. "
        "Wij vragen u om de relevante inkomensgegevens en eventuele aanvullende stukken aan te leveren, zodat wij uw situatie zorgvuldig kunnen herbeoordelen.\n\n"
        "Dit is een conceptreactie voor interne beoordeling.\n"
    )


async def _gemini_draft(raw_text: str, overview: Json) -> Optional[str]:
    if not GEMINI_API_KEY:
        return None

    # Minimal REST call (best effort). If it fails, we fall back.
    prompt = (
        "Schrijf een korte, neutrale conceptreactie in het Nederlands op deze bezwaarbrief. "
        "Gebruik een zakelijke toon. Noem dat het een concept is en dat een behandelaar dit controleert. "
        "Geen persoonsgegevens.\n\n"
        f"Context (samenvatting): {overview}\n\n"
        f"Bezwaarbrief (demo): {raw_text[:1500]}"
    )

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 220},
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, params={"key": GEMINI_API_KEY}, json=body)
            if r.status_code != 200:
                return None
            data = r.json()
            cand = (data.get("candidates") or [{}])[0]
            parts = (((cand.get("content") or {}).get("parts")) or [{}])
            text = parts[0].get("text")
            return text.strip() if isinstance(text, str) else None
    except Exception:
        return None


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
    if capability != "structure_bezwaar":
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Unknown capability"}}

    message = (params.get("message") or {})
    parts = message.get("parts") or []
    data_part = parts[0] if parts else {}
    data = data_part.get("data") or {}

    raw_text = str(data.get("raw_text", ""))
    entities = data.get("entities") or {}
    classification = data.get("classification") or {}
    snippets: List[str] = data.get("snippets") or []

    overview = {
        "type": classification.get("type", "Onbekend"),
        "reden": classification.get("reden", "Onbekend"),
        "datum": entities.get("datum", "Onbekend"),
        "onderwerp": entities.get("onderwerp", "Onbekend"),
        "bedrag": entities.get("bedrag", ""),
        "timeline": [
            "Ontvangst bezwaar (demo).",
            "Controle ontvankelijkheid en stukken.",
            "Beoordeling inhoudelijke gronden.",
            "Besluit en verzending reactie.",
        ],
        "snippets": snippets,
    }

    key_points = [
        "Datum van bezwaar lijkt plausibel (demo).",
        "Reden van bezwaar is herkenbaar (inkomen/hoogte aanslag) (demo).",
        "Vraag om onderbouwing met inkomensgegevens (demo).",
    ]

    actions = [
        "Vraag om inkomensgegevens van het relevante jaar (demo).",
        "Controleer betaal- en aanslaggeschiedenis (demo).",
        "Leg vast welke gegevens zijn gebruikt bij de beoordeling (demo).",
    ]

    draft = await _gemini_draft(raw_text, overview)
    if not draft:
        draft = _deterministic_draft(overview)

    result = {
        "overview": overview,
        "key_points": key_points,
        "actions": actions,
        "draft_response": draft,
    }
    return {"jsonrpc": "2.0", "id": req_id, "result": {"status": "ok", "data": result}}
