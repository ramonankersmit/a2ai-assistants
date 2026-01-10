from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

Json = Dict[str, Any]

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip()  # you set: gemini-2.5-flash
GEMINI_API_VERSION = os.getenv("GEMINI_API_VERSION", "").strip()  # you set: v1beta
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/")

# Demo tuning
GEMINI_MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "520"))
MIN_GEMINI_CHARS = int(os.getenv("MIN_GEMINI_CHARS", "220"))

log = logging.getLogger("a2a_bezwaar_agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="A2A Bezwaar Agent (Demo)", version="0.1.4")

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
            "Gemini enabled (key len=%s) base=%s model=%s version=%s max_tokens=%s min_chars=%s",
            len(GEMINI_API_KEY),
            GEMINI_BASE_URL,
            GEMINI_MODEL or "-",
            GEMINI_API_VERSION or "-",
            GEMINI_MAX_TOKENS,
            MIN_GEMINI_CHARS,
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
        "version": "0.1.4",
    }


def _deterministic_draft(overview: Json, key_points: List[str], actions: List[str]) -> str:
    type_ = overview.get("type", "Onbekend")
    onderwerp = overview.get("onderwerp", "uw bezwaar")
    datum = overview.get("datum", "onbekende datum")
    reden = overview.get("reden", "onbekend")
    bedrag = overview.get("bedrag", "")

    bullets = []
    for a in (actions or [])[:3]:
        bullets.append(f"- {a}")
    bullets_txt = "\n".join(bullets) if bullets else "- Aanvullende onderbouwing aanleveren (demo)."

    bedragzin = f" Het genoemde bedrag is {bedrag}." if bedrag else ""

    return (
        "Geachte heer/mevrouw,\n\n"
        f"Wij bevestigen de ontvangst van uw bezwaar d.d. {datum} over {onderwerp}.{bedragzin} "
        f"Op basis van uw brief lijkt de kern van het bezwaar: {reden}.\n\n"
        f"Om uw zaak ({type_}) zorgvuldig te beoordelen, hebben wij mogelijk aanvullende informatie nodig. "
        "Wij verzoeken u daarom om (waar relevant) de volgende stukken/gegevens aan te leveren:\n"
        f"{bullets_txt}\n\n"
        "Na ontvangst van de aanvullende informatie herbeoordelen wij de beslissing en ontvangt u een schriftelijke reactie. "
        "Dit is een concepttekst voor interne beoordeling; een behandelaar controleert en finaliseert de inhoud.\n\n"
        "Met vriendelijke groet,\n"
        "[Naam behandelaar] (concept)\n"
    )


def _candidate_versions() -> List[str]:
    base = ["v1beta", "v1"]
    if GEMINI_API_VERSION:
        return [GEMINI_API_VERSION] + [v for v in base if v != GEMINI_API_VERSION]
    return base


def _candidate_models() -> List[str]:
    # Default list includes 2.5-flash as requested, and a few common alternates.
    base = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
    ]
    if GEMINI_MODEL:
        return [GEMINI_MODEL] + [m for m in base if m != GEMINI_MODEL]
    return base


def _build_prompt(raw_text: str, overview: Json, key_points: List[str], actions: List[str]) -> str:
    # Explicitly ask for a non-trivial draft for demo purposes.
    # Keep it neutral, no PII, and clearly mark as concept.
    kp = "\n".join([f"- {x}" for x in (key_points or [])[:4]]) or "- (geen)"
    act = "\n".join([f"- {x}" for x in (actions or [])[:4]]) or "- (geen)"

    return (
        "Je bent een medewerker van een overheidsorganisatie. "
        "Schrijf een concept-reactie op een bezwaarbrief.\n\n"
        "VEREISTE FORMAT (houd exact aan):\n"
        "1) Aanhef: 'Geachte heer/mevrouw,'\n"
        "2) Alinia 1: ontvangstbevestiging + korte samenvatting van het bezwaar (max 2 zinnen)\n"
        "3) Alinia 2: wat we gaan doen (herbeoordeling) + welke informatie we mogelijk nog nodig hebben\n"
        "4) Bulletlijst: 3-5 concrete gevraagde stukken/gegevens\n"
        "5) Alinia 3: vervolgstappen + termijnindicatie (algemeen) + disclaimer concept\n"
        "6) Afsluiting: 'Met vriendelijke groet,' + '[Naam behandelaar] (concept)'\n\n"
        "LENGTE: 120–180 woorden. "
        "TOON: zakelijk, neutraal, zorgvuldig. "
        "GEEN PERSOONSGEGEVENS (gebruik placeholders).\n\n"
        f"Zaakoverzicht (demo): {overview}\n\n"
        "Belangrijke punten (demo):\n"
        f"{kp}\n\n"
        "Aanbevolen acties (demo):\n"
        f"{act}\n\n"
        "Bezwaarbrief (demo, ingekort):\n"
        f"{raw_text[:1500]}"
    )


async def _try_gemini_generate(prompt: str, version: str, model: str) -> Tuple[Optional[str], str]:
    url = f"{GEMINI_BASE_URL}/{version}/models/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.25, "maxOutputTokens": GEMINI_MAX_TOKENS},
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(url, params={"key": GEMINI_API_KEY}, json=body)

            if r.status_code != 200:
                txt = (r.text or "")[:400].replace("\n", " ")
                log.warning("Gemini failed: status=%s url=%s body=%s", r.status_code, url, txt)
                if r.status_code == 404:
                    return None, "http_404"
                return None, f"http_{r.status_code}"

            data = r.json()
            cand = (data.get("candidates") or [{}])[0]
            parts = (((cand.get("content") or {}).get("parts")) or [{}])
            text = parts[0].get("text")
            if isinstance(text, str) and text.strip():
                t = text.strip()
                # Guard: prevent overly short “one-liners” from ruining the demo
                if len(t) < MIN_GEMINI_CHARS:
                    log.warning("Gemini returned too-short text (%s chars) url=%s", len(t), url)
                    return None, "too_short"
                return t, "ok"

            log.warning("Gemini returned no text url=%s", url)
            return None, "no_text"

    except httpx.ConnectError as e:
        log.warning("Gemini connect error: %s", str(e))
        return None, "connect_error"
    except httpx.ReadTimeout as e:
        log.warning("Gemini timeout: %s", str(e))
        return None, "timeout"
    except Exception as e:
        log.warning("Gemini exception: %s", str(e))
        return None, "exception"


async def _gemini_draft(raw_text: str, overview: Json, key_points: List[str], actions: List[str]) -> Tuple[Optional[str], str]:
    if not GEMINI_API_KEY:
        return None, "no_api_key"

    prompt = _build_prompt(raw_text, overview, key_points, actions)

    last_reason = "unknown"
    tried: List[str] = []

    for version in _candidate_versions():
        for model in _candidate_models():
            tried.append(f"{version}:{model}")
            text, reason = await _try_gemini_generate(prompt, version, model)
            if text:
                log.info("Gemini success using %s:%s", version, model)
                return text, "ok"
            last_reason = reason

            # For non-404 reasons (403/quota/network), stop early
            if reason not in ("http_404",):
                log.info("Gemini aborting retries due to reason=%s tried=%s", reason, ",".join(tried))
                return None, reason

    log.info("Gemini exhausted model/version combos tried=%s", ",".join(tried))
    return None, "http_404_all"


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
        draft = f"[Bron: Fallback]\n{_deterministic_draft(overview, key_points, actions)}"

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
