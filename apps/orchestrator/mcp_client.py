"""
apps.orchestrator.mcp_client

Minimal MCP (Model Context Protocol) client for the demo.

This client is intentionally small and implements only what the orchestrator
needs for deterministic tool calls via MCP SSE transport.

Transport contract (minimal subset used by this demo):
- MCP server endpoints:
  - GET  /sse      : Server-Sent Events stream emitting JSON-RPC responses
  - POST /message  : JSON-RPC request ingress for tool calls

Operational flow for a tool call:
1) Open SSE stream (GET /sse)
2) POST JSON-RPC request to /message with method "tools/call"
3) Read SSE events until a JSON-RPC response arrives with matching "id"
4) Return "result" to caller

Note:
- The SSE response stream must be consumed exactly once and only while the
  `client.stream(...)` context is alive. Otherwise httpx may raise StreamConsumed.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Tuple

import httpx


async def _parse_sse_events(lines: AsyncIterator[str]) -> AsyncIterator[Tuple[str, str]]:
    """
    Parse an SSE stream into (event, data) tuples.

    This is a minimal SSE parser supporting:
      - `event:` lines (optional; default "message")
      - `data:` lines (one or multiple; joined by '\\n')
      - blank line as event delimiter

    Args:
        lines: Async iterator yielding decoded text lines (no newlines).

    Yields:
        Tuples of (event_name, data_string).
    """
    event = "message"
    data_lines: list[str] = []

    async for line in lines:
        # Blank line = dispatch current event
        if line == "":
            if data_lines:
                yield event, "\n".join(data_lines)
            event = "message"
            data_lines = []
            continue

        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            # Keep whitespace after "data:" consistent with SSE semantics
            data_lines.append(line.split(":", 1)[1].lstrip())

    # Stream ended; flush last event if present
    if data_lines:
        yield event, "\n".join(data_lines)


@dataclass(frozen=True)
class MCPToolCall:
    """
    Represents a single MCP tool call request in JSON-RPC form.
    """
    id: str
    name: str
    arguments: Dict[str, Any]

    def to_jsonrpc(self) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": self.id,
            "method": "tools/call",
            "params": {"name": self.name, "arguments": self.arguments},
        }


class MCPClient:
    """
    Minimal MCP client using SSE transport.

    The orchestrator uses this client for deterministic tool calls with
    small artificial latency introduced server-side.
    """

    def __init__(self, sse_url: str):
        """
        Args:
            sse_url: MCP SSE endpoint URL, typically "http://127.0.0.1:8000/sse".
        """
        self.sse_url = sse_url.rstrip("/")

    def _normalize_sse_url(self) -> str:
        """
        Ensure the configured URL ends with '/sse'. Accepts either base or SSE URL.

        Returns:
            A URL ending in '/sse'.
        """
        if self.sse_url.endswith("/sse"):
            return self.sse_url
        return f"{self.sse_url}/sse"

    @staticmethod
    def _message_url_from_sse_url(sse_url: str) -> str:
        """
        Derive the message ingress endpoint from the SSE endpoint.

        Example:
            http://127.0.0.1:8000/sse -> http://127.0.0.1:8000/message
        """
        return sse_url.replace("/sse", "/message")

    async def call_tool(self, name: str, arguments: Dict[str, Any], timeout_s: float = 8.0) -> Any:
        """
        Call an MCP tool over SSE transport.

        Transport contract (minimal subset used by this demo):
        - The MCP server exposes:
            - GET  /sse      : Server-Sent Events stream with JSON-RPC responses
            - POST /message  : JSON-RPC request ingress for tool calls
        - The orchestrator:
            1) Opens the SSE stream (GET /sse)
            2) Sends a JSON-RPC request to POST /message with method "tools/call"
            3) Waits on the SSE stream for a JSON-RPC response with matching "id"
            4) Returns the "result" field to the caller

        Important implementation note:
        - The SSE response stream must be consumed exactly once and only within the
          lifetime of the `client.stream(...)` context; otherwise httpx may raise
          StreamConsumed. This function therefore keeps a single active consumer
          and stops as soon as the matching response is received.

        Args:
            name: MCP tool name, e.g. "rules_lookup".
            arguments: JSON-serializable dict passed to the tool.
            timeout_s: Timeout for receiving the matching response on SSE.

        Returns:
            The JSON-decoded "result" field from the MCP server response.

        Raises:
            RuntimeError: If the MCP server returns a JSON-RPC error or the SSE stream
                         ends before a matching response is received.
            asyncio.TimeoutError: If no matching response is received within timeout_s.
            httpx.HTTPError: If POST /message fails (non-2xx).
        """
        sse_url = self._normalize_sse_url()
        message_url = self._message_url_from_sse_url(sse_url)

        call = MCPToolCall(id=str(uuid.uuid4()), name=name, arguments=arguments)
        req = call.to_jsonrpc()

        async with httpx.AsyncClient(timeout=None) as client:
            # 1) Open SSE stream
            async with client.stream(
                "GET",
                sse_url,
                headers={"Accept": "text/event-stream"},
            ) as stream:

                # 2) Post JSON-RPC call to message ingress
                async def post_call() -> None:
                    r = await client.post(message_url, json=req)
                    r.raise_for_status()

                post_task = asyncio.create_task(post_call())

                # 3) Single consumer over the SSE stream
                async def aiter_lines() -> AsyncIterator[str]:
                    async for raw in stream.aiter_lines():
                        # httpx yields decoded lines; keep them as-is
                        yield raw

                async def wait_for_response() -> Any:
                    async for ev, data in _parse_sse_events(aiter_lines()):
                        if ev != "message":
                            continue

                        # MCP server should emit JSON-RPC responses as data payload
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        if obj.get("id") != call.id:
                            continue

                        if "error" in obj and obj["error"] is not None:
                            raise RuntimeError(obj["error"])

                        return obj.get("result")

                    raise RuntimeError("SSE stream ended without response")

                try:
                    return await asyncio.wait_for(wait_for_response(), timeout=timeout_s)
                finally:
                    # Avoid dangling POST task if SSE handling fails early
                    if not post_task.done():
                        post_task.cancel()
