"""
services.mcp_tools.tools

Deterministic demo tools for:
- Toeslagen Check
- Bezwaar Assistent

No real persoonsgegevens; simple heuristics + dummy snippets.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional


def rules_lookup(regeling: Optional[str], jaar: Any) -> Dict[str, Any]:
    regeling = (regeling or "").strip().lower()
    try:
        jaar_i = int(jaar)
    except Exception:
        jaar_i = 2025

    # Small dummy dataset – deterministic
    base = {
        "regeling": regeling or "onbekend",
        "jaar": jaar_i,
        "voorwaarden": [],
        "opmerking": "Demo-voorwaarden (niet juridisch bindend).",
    }

    if regeling in ("huur", "huurtoeslag"):
        base["voorwaarden"] = [
            {"id": "H1", "text": "U bent 18 jaar of ouder."},
            {"id": "H2", "text": "Uw huur is binnen de (demo) grens voor het gekozen jaar."},
            {"id": "H3", "text": "Uw inkomen en vermogen vallen binnen (demo) grenzen."},
            {"id": "H4", "text": "U staat ingeschreven op het adres."},
        ]
    elif regeling in ("zorg", "zorgtoeslag"):
        base["voorwaarden"] = [
            {"id": "Z1", "text": "U bent 18 jaar of ouder."},
            {"id": "Z2", "text": "U heeft een Nederlandse zorgverzekering."},
            {"id": "Z3", "text": "Uw inkomen en vermogen vallen binnen (demo) grenzen."},
        ]
    else:
        base["voorwaarden"] = [
            {"id": "X1", "text": "Regeling onbekend: kies huur of zorg (demo)."},
        ]

    # Tiny year variation (still deterministic)
    if jaar_i >= 2025 and regeling in ("huur", "huurtoeslag"):
        base["voorwaarden"].append({"id": "H5", "text": "Let op: (demo) grenswaarden kunnen per jaar verschillen."})

    return base


def doc_checklist(regeling: Optional[str], situatie: Optional[str]) -> Dict[str, Any]:
    regeling = (regeling or "").strip().lower()
    situatie = (situatie or "").strip().lower()

    docs = [
        "Identiteitsbewijs (kopie/gegevens)",
        "Inkomensgegevens (loonstrook/jaaropgave)",
    ]

    if regeling in ("huur", "huurtoeslag"):
        docs += [
            "Huurcontract",
            "Overzicht huurprijs + servicekosten",
        ]
    if regeling in ("zorg", "zorgtoeslag"):
        docs += [
            "Polis/gegevens zorgverzekering",
        ]

    if "partner" in situatie or "samen" in situatie:
        docs += ["Gegevens partner (inkomen/vermogen)"]

    if "kind" in situatie or "gezin" in situatie:
        docs += ["Gegevens kinderen (indien relevant)"]

    return {"regeling": regeling or "onbekend", "situatie": situatie or "", "documenten": docs}


def risk_notes(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Rule-based attention points based on typical demo inputs.
    Expects keys like: inkomen, vermogen, jaar, situatie.
    """
    notes: List[Dict[str, str]] = []

    def _to_float(x) -> float:
        try:
            return float(str(x).replace(",", "."))
        except Exception:
            return 0.0

    inkomen = _to_float(inputs.get("inkomen", 0))
    vermogen = _to_float(inputs.get("vermogen", 0))
    situatie = str(inputs.get("situatie", "")).lower()

    # Simple thresholds (demo)
    if inkomen >= 45000:
        notes.append({"code": "R1", "text": "Inkomen lijkt hoog; controleer (demo) inkomensgrenzen."})
    elif 0 < inkomen < 15000:
        notes.append({"code": "R2", "text": "Laag inkomen: let op (demo) bewijsstukken en wijzigingen door het jaar."})

    if vermogen >= 80000:
        notes.append({"code": "R3", "text": "Vermogen lijkt hoog; controleer (demo) vermogensgrenzen."})

    if "wissel" in situatie or "scheid" in situatie:
        notes.append({"code": "R4", "text": "Gezinssituatie verandert: wijzigingen tijdig doorgeven (demo)."})
    if "student" in situatie:
        notes.append({"code": "R5", "text": "Studenten: let op inkomen bijbaan en inschrijving (demo)."})
    if not notes:
        notes.append({"code": "R0", "text": "Geen opvallende aandachtspunten op basis van demo-regels."})

    return {"aandachtspunten": notes}


def extract_entities(text: str) -> Dict[str, Any]:
    """
    Heuristic entity extraction for demo.
    Extracts: date, amount, subject keywords.
    """
    t = text or ""
    # Date patterns (very rough)
    date_match = re.search(r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b", t)
    amount_match = re.search(r"\b€?\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\b", t)

    onderwerp = "onbekend"
    tl = t.lower()
    if "toeslag" in tl:
        onderwerp = "toeslag"
    if "huur" in tl:
        onderwerp = "huurtoeslag"
    if "zorg" in tl:
        onderwerp = "zorgtoeslag"
    if "boete" in tl or "naheff" in tl:
        onderwerp = "boete/naheffing"
    if "aanslag" in tl:
        onderwerp = "aanslag"

    return {
        "datum": date_match.group(1) if date_match else None,
        "bedrag": amount_match.group(1) if amount_match else None,
        "onderwerp": onderwerp,
    }


def classify_case(text: str) -> Dict[str, Any]:
    """
    Rule-based classification for demo.
    """
    tl = (text or "").lower()

    case_type = "Algemeen bezwaar"
    reason = "Onvoldoende informatie"

    if "toeslag" in tl:
        case_type = "Toeslagen"
        reason = "Berekening/grondslag betwist"
    if "boete" in tl or "naheff" in tl:
        case_type = "Boete/Naheffing"
        reason = "Verwijtbaarheid/proportionaliteit betwist"
    if "aanslag" in tl:
        case_type = "Aanslag"
        reason = "Hoogte/grondslag betwist"
    if "termijn" in tl or "te laat" in tl:
        reason = "Termijn/ontvankelijkheid"

    return {"type": case_type, "reason": reason, "confidence": 0.65}


def policy_snippets(case_type: Optional[str]) -> Dict[str, Any]:
    """
    Dummy policy snippets per case type.
    """
    ct = (case_type or "").lower()
    if "toeslag" in ct:
        snippets = [
            "Beoordeel de grondslag en relevante inkomens-/vermogensgegevens (demo).",
            "Check wijzigingen in situatie binnen het berekeningsjaar (demo).",
        ]
    elif "boete" in ct or "naheff" in ct:
        snippets = [
            "Toets proportionaliteit en verwijtbaarheid (demo).",
            "Controleer of de motivering voldoende is en termijnen kloppen (demo).",
        ]
    else:
        snippets = [
            "Controleer de feiten, berekening en motivering (demo).",
            "Check ontvankelijkheid, termijnen en gevraagde stukken (demo).",
        ]
    return {"snippets": snippets}
