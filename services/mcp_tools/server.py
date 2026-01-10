"""
services.mcp_tools.server

Standalone MCP tool server using SSE transport.

Endpoints (minimal MCP SSE subset for this demo):
- GET  /sse     : Server-Sent Events stream with JSON-RPC responses
- POST /message : JSON-RPC ingress for tool calls (method: "tools/call")

The orchestrator flow:
1) Opens /sse
2) POSTs JSON-RPC request to /message
3) Waits on /sse for a JSON-RPC response with matching id
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .tools import (
    classify_case,
    doc_checklist,
    extract_entities,
    policy_snippets,
    risk_notes,
    rules_lookup,
)

app = FastAPI(title="MCP Tools (Demo)", version="0.1.0")

# CORS: keep it permissive for local demo
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

# Connected SSE clients (each gets a queue)
_clients: List[asyncio.Queue] = []


async def _publish_sse(payload: Dict[str, Any]) -> None:
    """Broadcast a JSON-serializable payload to all SSE clients."""
    # Copy list to avoid mutation issues during iteration
    for q in list(_clients):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            # For demo: drop if client is too slow
            pass


async def _call_tool(tool_name: str, arguments: Dict[str, Any]) -> Any:
    """
    Deterministic tool dispatcher with fake latency 300–700ms.
    """
    # Fake latency (non-deterministic timing is fine; results remain deterministic)
    await asyncio.sleep(random.uniform(0.3, 0.7))

    if tool_name == "rules_lookup":
        return rules_lookup(arguments.get("regeling"), arguments.get("jaar"))
    if tool_name == "doc_checklist":
        return doc_checklist(arguments.get("regeling"), arguments.get("situatie"))
    if tool_name == "risk_notes":
        return risk_notes(arguments)

    if tool_name == "extract_entities":
        return extract_entities(arguments.get("text", ""))
    if tool_name == "classify_case":
        return classify_case(arguments.get("text", ""))
    if tool_name == "policy_snippets":
        return policy_snippets(arguments.get("type"))

    raise ValueError(f"Unknown tool: {tool_name}")


@app.get("/sse")
async def sse():
    """
    SSE stream for JSON-RPC responses.

    Emits:
      event: message
      data: <json-string>
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _clients.append(q)

    async def gen():
        try:
            # Small initial comment helps some proxies/browsers
            yield ": connected\n\n"
            while True:
                payload = await q.get()
                data = json.dumps(payload, ensure_ascii=False)
                yield f"event: message\ndata: {data}\n\n"
        finally:
            try:
                _clients.remove(q)
            except ValueError:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/message")
async def message(request: Request):
    """
    JSON-RPC ingress for MCP SSE transport.

    Expected request shape:
      {
        "jsonrpc": "2.0",
        "id": "<string>",
        "method": "tools/call",
        "params": { "name": "<tool>", "arguments": { ... } }
      }

    Returns 200 with the JSON-RPC response AND broadcasts it on SSE.
    """
    try:
        msg = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status_code=200,
        )

    req_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method != "tools/call":
        resp = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}
        await _publish_sse(resp)
        return JSONResponse(resp, status_code=200)

    tool_name = params.get("name")
    arguments = params.get("arguments") or {}

    try:
        result = await _call_tool(tool_name, arguments)
        resp = {"jsonrpc": "2.0", "id": req_id, "result": result}
    except Exception as e:
        resp = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(e)}}

    await _publish_sse(resp)
    return JSONResponse(resp, status_code=200)
