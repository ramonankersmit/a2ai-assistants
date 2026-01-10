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
GEMINI_MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "1200"))
MIN_GEMINI_WORDS = int(os.getenv("MIN_GEMINI_WORDS", "90"))
TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.6"))

log = logging.getLogger("a2a_bezwaar_agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Prevent leaking ?key=... via httpx info logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = FastAPI(title="A2A Bezwaar Agent (Demo)", version="0.1.7")

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
        "version": "0.1.7",
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
    return (
        "Je bent een medewerker van een overheidsorganisatie.\n"
        "Schrijf een concept-reactie op een bezwaarbrief.\n\n"
        "VEREISTE FORMAT (houd exact aan):\n"
        "1) Aanhef: 'Geachte heer/mevrouw,'\n"
        "2) Alinia 1: ontvangstbevestiging + korte samenvatting (max 2 zinnen)\n"
        "3) Alinia 2: herbeoordeling + welke info nog nodig is\n"
        "4) Bulletlijst: 3-5 concrete gevraagde stukken/gegevens\n"
        "5) Alinia 3: vervolgstappen + algemene termijnindicatie + disclaimer concept\n"
        "6) Afsluiting: 'Met vriendelijke groet,' + '[Naam behandelaar] (concept)'\n\n"
        "LENGTE: 120–180 woorden.\n"
        "TOON: zakelijk, neutraal, zorgvuldig.\n"
        "GEEN PERSOONSGEGEVENS: gebruik placeholders.\n"
        "Schrijf volledig; niet dubbel beginnen; niet afbreken."
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


def _extract_text_and_finish(data: Json) -> Tuple[str, str]:
    """
    candidateCount=1: join all parts from candidates[0] and read finishReason.
    """
    cands = data.get("candidates") or []
    if not isinstance(cands, list) or not cands or not isinstance(cands[0], dict):
        return "", ""

    cand0 = cands[0]
    finish = str(cand0.get("finishReason") or "")

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

    return "\n".join(chunks).strip(), finish


def _looks_truncated(text: str, finish_reason: str) -> bool:
    if not text:
        return True

    # If API says we hit max tokens, it is truncated. :contentReference[oaicite:1]{index=1}
    if finish_reason == "MAX_TOKENS":
        return True

    # Missing the expected signature block -> very likely incomplete
    if "Met vriendelijke groet" not in text or "(concept)" not in text:
        # Allow if user deliberately didn't want it, but for this demo it's required
        return True

    # Ends in a mid-word or without punctuation (heuristic)
    tail = text.strip()[-30:]
    if re.search(r"[A-Za-zÀ-ÿ]{3,}$", tail) and not re.search(r"[.!?]\s*$", text.strip()):
        return True

    return False


def _merge_continuation(base: str, cont: str) -> str:
    """
    Best-effort merge: if continuation repeats the start, drop duplicates.
    """
    b = (base or "").strip()
    c = (cont or "").strip()
    if not c:
        return b

    # If continuation contains full draft (starts with Geachte...), prefer it
    if c.startswith("Geachte heer/mevrouw"):
        return c

    # Otherwise append
    return (b + "\n\n" + c).strip()


async def _gemini_generate(contents: List[Json], *, system_instruction: str) -> Tuple[Optional[str], str, str]:
    """
    Returns (text_or_none, reason, finishReason)
    """
    if not GEMINI_API_KEY:
        return None, "no_api_key", ""

    url = f"{GEMINI_BASE_URL}/{GEMINI_API_VERSION}/models/{GEMINI_MODEL}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": contents,
        "generationConfig": {
            "temperature": TEMPERATURE,
            "maxOutputTokens": GEMINI_MAX_TOKENS,
            "candidateCount": 1,
        },
    }

    # Use header to avoid key appearing in URLs anywhere (best practice for logs)
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, headers=headers, json=body)

            if r.status_code != 200:
                txt = (r.text or "")[:400].replace("\n", " ")
                log.warning("Gemini failed: status=%s url=%s body=%s", r.status_code, url, txt)
                return None, f"http_{r.status_code}", ""

            data = r.json()
            text, finish = _extract_text_and_finish(data)
            words = _word_count(text)

            log.info("Gemini response: finishReason=%s words=%s", finish or "-", words)

            if not text:
                return None, "no_text", finish
            if words < MIN_GEMINI_WORDS:
                log.warning("Gemini too short (%s words). sample=%r", words, text[:140])
                return None, "too_short", finish

            return text, "ok", finish

    except httpx.ConnectError as e:
        log.warning("Gemini connect error: %s", str(e))
        return None, "connect_error", ""
    except httpx.ReadTimeout as e:
        log.warning("Gemini timeout: %s", str(e))
        return None, "timeout", ""
    except Exception as e:
        log.warning("Gemini exception: %s", str(e))
        return None, "exception", ""


async def _gemini_draft(raw_text: str, overview: Json, key_points: List[str], actions: List[str]) -> Tuple[Optional[str], str]:
    sys = _system_instruction_text()
    user = _user_prompt(raw_text, overview, key_points, actions)

    # Turn 1
    contents_1 = [{"role": "user", "parts": [{"text": user}]}]
    t1, reason1, finish1 = await _gemini_generate(contents_1, system_instruction=sys)
    if not t1:
        # If too short: one explicit retry
        if reason1 == "too_short":
            retry_user = user + "\n\nBELANGRIJK: schrijf volledig 120–180 woorden en rond af met afsluiting."
            t1b, reason1b, finish1b = await _gemini_generate(
                [{"role": "user", "parts": [{"text": retry_user}]}],
                system_instruction=sys,
            )
            if not t1b:
                return None, reason1b
            t1, finish1 = t1b, finish1b
        else:
            return None, reason1

    # If it looks truncated, do a continuation turn
    if _looks_truncated(t1, finish1):
        cont_request = (
            "Ga verder vanaf waar je stopte en rond de conceptbrief volledig af. "
            "Herhaal geen eerdere tekst. Voeg de afsluiting toe (Met vriendelijke groet + [Naam behandelaar] (concept))."
        )
        contents_2 = [
            {"role": "user", "parts": [{"text": user}]},
            {"role": "model", "parts": [{"text": t1}]},
            {"role": "user", "parts": [{"text": cont_request}]},
        ]
        t2, reason2, finish2 = await _gemini_generate(contents_2, system_instruction=sys)
        if t2:
            merged = _merge_continuation(t1, t2)
            # If still incomplete, fall back (demo stability)
            if _looks_truncated(merged, finish2):
                return None, "still_truncated"
            return merged, "ok"
        return None, f"continue_{reason2}"

    return t1, "ok"


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
