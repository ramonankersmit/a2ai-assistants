from __future__ import annotations

import asyncio
import json
import random
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import httpx

Json = Dict[str, Any]


def _parse_sse_events(lines):
    """Very small SSE parser. Yields (event, data_str)."""
    event = "message"
    data_lines = []
    for line in lines:
        if line == "":
            if data_lines:
                yield event, "\n".join(data_lines)
            event = "message"
            data_lines = []
            continue
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].lstrip())
    if data_lines:
        yield event, "\n".join(data_lines)


@dataclass
class MCPClient:
    sse_url: str

    async def call_tool(self, name: str, arguments: Json, timeout_s: float = 10.0) -> Json:
        """
        Calls MCP tool via SSE transport:
          - open SSE at /sse -> receive endpoint event with sse_id + post_url
          - POST JSON-RPC to post_url with header X-SSE-ID
          - wait for response on SSE event 'message' with matching id
        """
        req_id = str(uuid.uuid4())
        rpc = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            async with client.stream("GET", self.sse_url) as stream:
                sse_id: Optional[str] = None
                post_url: Optional[str] = None

                async def aiter():
                    async for raw in stream.aiter_lines():
                        yield raw.rstrip("\r")

                # Wait for endpoint
                async for ev, data in _parse_sse_events(aiter()):
                    if ev == "endpoint":
                        payload = json.loads(data)
                        sse_id = payload.get("sse_id")
                        post_url = payload.get("post_url")
                        break

                if not sse_id or not post_url:
                    raise RuntimeError("MCP handshake failed (no endpoint)")

                # Fake latency (as per spec)
                await asyncio.sleep(random.uniform(0.3, 0.7))

                # POST request (no direct response body needed)
                await client.post(post_url, headers={"X-SSE-ID": sse_id}, json=rpc)

                # Wait response
                async def wait_for_response() -> Json:
                    async for ev, data in _parse_sse_events(aiter()):
                        if ev != "message":
                            continue
                        msg = json.loads(data)
                        if msg.get("id") == req_id:
                            if "error" in msg:
                                raise RuntimeError(f"MCP tool error: {msg['error']}")
                            return msg.get("result") or {}
                    raise RuntimeError("MCP SSE ended before response")

                return await asyncio.wait_for(wait_for_response(), timeout=timeout_s)
