from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .tools import classify_case, doc_checklist, extract_entities, policy_snippets, risk_notes, rules_lookup

load_dotenv()

Json = Dict[str, Any]

app = FastAPI(title="MCP Tools (Demo)", version="0.1.0")

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

# Per-SSE connection queues
_queues: Dict[str, "asyncio.Queue[Json]"] = {}
_lock = asyncio.Lock()


async def _new_sse_id() -> str:
    async with _lock:
        sse_id = str(uuid.uuid4())
        _queues[sse_id] = asyncio.Queue()
        return sse_id


async def _get_queue(sse_id: str) -> Optional["asyncio.Queue[Json]"]:
    async with _lock:
        return _queues.get(sse_id)


async def _drop_queue(sse_id: str) -> None:
    async with _lock:
        _queues.pop(sse_id, None)


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/sse")
async def sse(request: Request):
    """MCP SSE transport endpoint."""
    sse_id = await _new_sse_id()
    post_url = "http://127.0.0.1:8000/message"

    async def gen():
        # Endpoint handshake
        handshake = {"sse_id": sse_id, "post_url": post_url}
        yield f"event: endpoint\ndata: {json.dumps(handshake)}\n\n"

        q = await _get_queue(sse_id)
        if not q:
            return

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                yield f"event: message\ndata: {json.dumps(msg)}\n\n"
        finally:
            await _drop_queue(sse_id)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/message")
async def message(
    rpc: Json = Body(...),
    x_sse_id: Optional[str] = Header(default=None, convert_underscores=False, alias="X-SSE-ID"),
):
    if not x_sse_id:
        raise HTTPException(400, "Missing X-SSE-ID header")
    q = await _get_queue(x_sse_id)
    if not q:
        raise HTTPException(404, "Unknown SSE session")

    try:
        method = rpc.get("method")
        req_id = rpc.get("id")
        if method != "tools/call":
            await q.put({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}})
            return {"ok": True}

        params = rpc.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}

        result: Json
        if name == "rules_lookup":
            result = rules_lookup(str(args.get("regeling", "Huurtoeslag")), int(args.get("jaar", 2024)))
        elif name == "doc_checklist":
            result = doc_checklist(str(args.get("regeling", "Huurtoeslag")), str(args.get("situatie", "Alleenstaand")))
        elif name == "risk_notes":
            result = risk_notes(
                str(args.get("regeling", "Huurtoeslag")),
                int(args.get("jaar", 2024)),
                str(args.get("situatie", "Alleenstaand")),
                bool(args.get("loonOfVermogen", True)),
            )
        elif name == "extract_entities":
            result = extract_entities(str(args.get("text", "")))
        elif name == "classify_case":
            result = classify_case(str(args.get("text", "")))
        elif name == "policy_snippets":
            result = policy_snippets(str(args.get("type", "Algemeen bezwaar")))
        else:
            await q.put({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Unknown tool"}})
            return {"ok": True}

        await q.put({"jsonrpc": "2.0", "id": req_id, "result": result})
        return {"ok": True}
    except Exception as e:
        await q.put({"jsonrpc": "2.0", "id": rpc.get("id"), "error": {"code": -32000, "message": str(e)}})
        return {"ok": True}
