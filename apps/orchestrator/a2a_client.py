from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict

import httpx

Json = Dict[str, Any]


@dataclass
class A2AClient:
    base_url: str

    async def message_send(self, capability: str, payload: Json, timeout_s: float = 20.0) -> Json:
        req_id = str(uuid.uuid4())
        rpc = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "message/send",
            "params": {
                "capability": capability,
                "message": {
                    "kind": "message",
                    "messageId": str(uuid.uuid4()),
                    "role": "user",
                    "parts": [
                        {
                            "kind": "data",
                            "metadata": {"mimeType": "application/json"},
                            "data": payload,
                        }
                    ],
                },
            },
        }
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(self.base_url, json=rpc)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(f"A2A error: {data['error']}")
            return (data.get("result") or {}).get("data") or {}
