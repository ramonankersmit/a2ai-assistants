from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

Json = Dict[str, Any]

app = FastAPI(title="A2A Toeslagen Agent (Demo)", version="0.1.0")

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
        "name": "toeslagen-agent",
        "description": "Verrijkt toeslagen-checklist en aandachtspunten met B1-uitleg en prioriteit (demo).",
        "url": "http://localhost:8010/",
        "capabilities": ["explain_toeslagen"],
        "protocol": "a2a-jsonrpc",
    }


def _priority_for(text: str) -> str:
    t = text.lower()
    if "grens" in t or "inkomen" in t or "vermogen" in t:
        return "hoog"
    if "controle" in t or "contract" in t:
        return "midden"
    return "laag"


def _b1_explain(item_text: str) -> str:
    # 1-2 sentences, B1-ish.
    base = item_text.rstrip(".")
    if "inkomen" in base.lower():
        return "We controleren of uw inkomen niet te hoog is. Lever uw inkomensgegevens aan als bewijs."
    if "huurcontract" in base.lower():
        return "Dit laat zien dat u de woning echt huurt. Stuur een kopie van het huurcontract mee."
    if "vermogen" in base.lower():
        return "We kijken ook naar spaargeld en beleggingen. Geef uw vermogen op over het juiste jaar."
    if "adres" in base.lower():
        return "U moet op het adres staan ingeschreven. Controleer dit in de BRP."
    return "Dit punt is belangrijk voor de beoordeling. Zorg dat u de informatie op tijd aanlevert."


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
    if capability != "explain_toeslagen":
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Unknown capability"}}

    message = (params.get("message") or {})
    parts = message.get("parts") or []
    data_part = parts[0] if parts else {}
    data = data_part.get("data") or {}

    items: List[Json] = data.get("items") or []
    enriched: List[Json] = []
    for it in items:
        text = str(it.get("text", ""))
        enriched.append(
            {
                "category": it.get("category"),
                "text": text,
                "priority": _priority_for(text),
                "b1_explanation": _b1_explain(text),
            }
        )

    result = {"items": enriched}
    return {"jsonrpc": "2.0", "id": req_id, "result": {"status": "ok", "data": result}}
