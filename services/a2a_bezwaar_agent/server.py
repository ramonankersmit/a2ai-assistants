from __future__ import annotations

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

# Demo tuning
GEMINI_MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "900"))
MIN_GEMINI_WORDS = int(os.getenv("MIN_GEMINI_WORDS", "90"))  # ~120–180 woorden target, dus 90+ als ondergrens
TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "1.0"))

log = logging.getLogger("a2a_bezwaar_agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Prevent leaking ?key=... via httpx info logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = FastAPI(title="A2A Bezwaar Agent (Demo)", version="0.1.6")

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
        log.info(
            "Gemini enabled (key len=%s) base=%s version=%s model=%s max_tokens=%s min_words=%s temp=%s",
            len(GEMINI_API_KEY),
            GEMINI_BASE_URL,
            GEMINI_API_VERSION,
            GEMINI_MODEL,
            GEMINI_MAX_TOKENS,
            MIN_GEMINI_WORDS,
            TEMPERATURE,
        )
    else:
        log.info("Gemini disabled (GEMINI_API_KEY missing) — using deterministic fallback")


@app.get("/.well-known/agent-card.json")
async def agent_card():
    return {
        "name": "bezwaar-agent",
        "description": "Structureert bezwaarbrieven en genereert conceptreactie (Gemini of fallback) (demo).",
        "url": "http://localhost:8020/",
        "capabilities": ["structure_bezwaar"],
        "protocol": "a2a-jsonrpc",
        "version": "0.1.6",
    }


def _word_count(s: str) -> int:
    return len(re.findall(r"\b\w+\b", s or ""))


def _deterministic_draft(overview: Json, actions: List[str]) -> str:
    type_ = overview.get("type", "Onbekend")
    onderwerp = overview.get("onderwerp", "uw bezwaar")
    datum = overview.get("datum", "onbekende datum")
    reden = overview.get("reden", "onbekend")
    bedrag = overview.get("bedrag", "")

    bullets = [f"- {a}" for a in (actions or [])[:5]] or ["- Aanvullende onderbouwing aanleveren (demo)."]
    bedragzin = f" Het genoemde bedrag is {bedrag}." if bedrag else ""

    return (
        "Geachte heer/mevrouw,\n\n"
        f"Wij bevestigen de ontvangst van uw bezwaar d.d. {datum} over {onderwerp}.{bedragzin} "
        f"Op basis van uw brief lijkt de kern van het bezwaar: {reden}.\n\n"
        f"Om uw zaak ({type_}) zorgvuldig te beoordelen, hebben wij mogelijk aanvullende informatie nodig. "
        "Wij verzoeken u daarom om (waar relevant) de volgende stukken/gegevens aan te leveren:\n"
        + "\n".join(bullets)
        + "\n\n"
        "Na ontvangst van de aanvullende informatie herbeoordelen wij de beslissing en ontvangt u een schriftelijke reactie. "
        "Dit is een concepttekst voor interne beoordeling; een behandelaar controleert en finaliseert de inhoud.\n\n"
        "Met vriendelijke groet,\n"
        "[Naam behandelaar] (concept)\n"
    )


def _system_instruction_text() -> str:
    # Official API supports systemInstruction in the request body. :contentReference[oaicite:2]{index=2}
    return (
        "Je bent een medewerker van een overheidsorganisatie.\n"
        "Schrijf een concept-reactie op een bezwaarbrief.\n\n"
        "VEREISTE FORMAT (houd exact aan):\n"
        "1) Aanhef: 'Geachte heer/mevrouw,'\n"
        "2) Alinia 1: ontvangstbevestiging + korte samenvatting van het bezwaar (max 2 zinnen)\n"
        "3) Alinia 2: wat we gaan doen (herbeoordeling) + welke info we nog nodig hebben\n"
        "4) Bulletlijst: 3-5 concrete gevraagde stukken/gegevens\n"
        "5) Alinia 3: vervolgstappen + algemene termijnindicatie + disclaimer concept\n"
        "6) Afsluiting: 'Met vriendelijke groet,' + '[Naam behandelaar] (concept)'\n\n"
        "LENGTE: 120–180 woorden.\n"
        "TOON: zakelijk, neutraal, zorgvuldig.\n"
        "GEEN PERSOONSGEGEVENS: gebruik placeholders.\n"
        "Schrijf volledig; niet afbreken of dubbel beginnen."
    )


def _user_prompt(raw_text: str, overview: Json, key_points: List[str], actions: List[str]) -> str:
    kp = "\n".join([f"- {x}" for x in (key_points or [])[:4]]) or "- (geen)"
    act = "\n".join([f"- {x}" for x in (actions or [])[:4]]) or "- (geen)"
    return (
        f"Zaakoverzicht (demo): {overview}\n\n"
        "Belangrijke punten (demo):\n"
        f"{kp}\n\n"
        "Aanbevolen acties (demo):\n"
        f"{act}\n\n"
        "Bezwaarbrief (demo, ingekort):\n"
        f"{raw_text[:1500]}"
    )


def _extract_text_single_candidate(data: Json) -> str:
    """
    We use candidateCount=1 to avoid partial/duplicate outputs.
    Join all parts in the single candidate.
    """
    cands = data.get("candidates") or []
    if not isinstance(cands, list) or not cands:
        return ""

    cand0 = cands[0] if isinstance(cands[0], dict) else {}
    content = cand0.get("content") or {}
    parts = (content.get("parts") or []) if isinstance(content, dict) else []
    if not isinstance(parts, list):
        parts = []

    chunks: List[str] = []
    for p in parts:
        if isinstance(p, dict):
            t = p.get("text")
            if isinstance(t, str) and t.strip():
                chunks.append(t.strip())

    return "\n".join(chunks).strip()


async def _gemini_generate(contents: List[Json], *, system_instruction: str) -> Tuple[Optional[str], str, Json]:
    """
    Returns (text_or_none, reason, raw_response_json)
    """
    if not GEMINI_API_KEY:
        return None, "no_api_key", {}

    url = f"{GEMINI_BASE_URL}/{GEMINI_API_VERSION}/models/{GEMINI_MODEL}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": contents,
        "generationConfig": {
            "temperature": TEMPERATURE,
            "maxOutputTokens": GEMINI_MAX_TOKENS,
            # Keep to 1 candidate for stability
            "candidateCount": 1,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.post(url, params={"key": GEMINI_API_KEY}, json=body)
            if r.status_code != 200:
                txt = (r.text or "")[:400].replace("\n", " ")
                log.warning("Gemini failed: status=%s url=%s body=%s", r.status_code, url, txt)
                return None, f"http_{r.status_code}", {}

            data = r.json()
            text = _extract_text_single_candidate(data)

            # Log useful diagnostics (no key leakage)
            words = _word_count(text)
            parts_count = 0
            try:
                cand0 = (data.get("candidates") or [{}])[0]
                parts_count = len(((cand0.get("content") or {}).get("parts") or []))
                finish = cand0.get("finishReason")
            except Exception:
                finish = None
            log.info("Gemini response: parts=%s words=%s finishReason=%s", parts_count, words, finish)

            if not text:
                return None, "no_text", data
            if words < MIN_GEMINI_WORDS:
                # Show sample for debugging (first 140 chars)
                log.warning("Gemini too short (%s words). sample=%r", words, text[:140])
                return None, "too_short", data

            return text, "ok", data

    except httpx.ConnectError as e:
        log.warning("Gemini connect error: %s", str(e))
        return None, "connect_error", {}
    except httpx.ReadTimeout as e:
        log.warning("Gemini timeout: %s", str(e))
        return None, "timeout", {}
    except Exception as e:
        log.warning("Gemini exception: %s", str(e))
        return None, "exception", {}


async def _gemini_draft(raw_text: str, overview: Json, key_points: List[str], actions: List[str]) -> Tuple[Optional[str], str]:
    """
    1) Single-turn call with systemInstruction.
    2) If too short: do a multi-turn "continue and finish" call (user→model→user).
       This uses roles supported by the API for multi-turn. :contentReference[oaicite:3]{index=3}
    """
    sys = _system_instruction_text()
    user = _user_prompt(raw_text, overview, key_points, actions)

    # Turn 1
    contents_1 = [{"role": "user", "parts": [{"text": user}]}]
    t1, reason1, raw1 = await _gemini_generate(contents_1, system_instruction=sys)
    if t1:
        return t1, "ok"
    if reason1 != "too_short":
        return None, reason1

    # Turn 2 (continue): include the model's short response + explicit continuation request
    # If we have the model text, use it; otherwise just ask again.
    model_text = ""
    try:
        model_text = _extract_text_single_candidate(raw1)
    except Exception:
        model_text = ""

    contents_2 = [
        {"role": "user", "parts": [{"text": user}]},
        {"role": "model", "parts": [{"text": model_text or "(te kort antwoord)"}]},
        {"role": "user", "parts": [{"text": "Ga door en maak de conceptbrief volledig af volgens het format en 120–180 woorden."}]},
    ]
    t2, reason2, _ = await _gemini_generate(contents_2, system_instruction=sys)
    if t2:
        return t2, "ok"
    return None, reason2


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
        "reden": classification.get("reden", classification.get("reason", "Onbekend")),
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
        "Bezwaar bevat een duidelijke betwisting van de grondslag/hoogte (demo).",
        "Vraag om onderbouwing met inkomensgegevens (demo).",
        "Controleer termijnen en ontvankelijkheid (demo).",
    ]

    actions = [
        "Vraag om inkomensgegevens van het relevante jaar (demo).",
        "Controleer betaal- en aanslaggeschiedenis (demo).",
        "Leg vast welke gegevens zijn gebruikt bij de beoordeling (demo).",
    ]

    draft, reason = await _gemini_draft(raw_text, overview, key_points, actions)
    if draft:
        draft_source = "gemini"
        draft = f"[Bron: Gemini]\n{draft}"
    else:
        draft_source = "fallback"
        draft = f"[Bron: Fallback]\n{_deterministic_draft(overview, actions)}"

    log.info("draft_source=%s reason=%s", draft_source, reason)

    result = {
        "overview": overview,
        "key_points": key_points,
        "actions": actions,
        "draft_source": draft_source,
        "draft_source_reason": reason,
        "draft_response": draft,
    }
    return {"jsonrpc": "2.0", "id": req_id, "result": {"status": "ok", "data": result}}
