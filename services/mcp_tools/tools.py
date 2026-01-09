from __future__ import annotations

import re
from typing import Any, Dict, List

Json = Dict[str, Any]


DUMMY_RULES = {
    ("Huurtoeslag", 2024): [
        "U staat ingeschreven op het adres van de huurwoning.",
        "Uw huur ligt binnen de grenzen voor huurtoeslag.",
        "Uw inkomen en vermogen zijn niet te hoog.",
        "U huurt een zelfstandige woonruimte.",
    ],
    ("Zorgtoeslag", 2024): [
        "U bent 18 jaar of ouder.",
        "U heeft een Nederlandse zorgverzekering.",
        "Uw inkomen is niet te hoog.",
    ],
}


def rules_lookup(regeling: str, jaar: int) -> Json:
    regels = DUMMY_RULES.get((regeling, jaar)) or DUMMY_RULES.get((regeling, 2024)) or []
    if not regels:
        regels = [
            "Algemene voorwaarde 1 (demo).",
            "Algemene voorwaarde 2 (demo).",
        ]
    return {"regeling": regeling, "jaar": jaar, "voorwaarden": regels}


def doc_checklist(regeling: str, situatie: str) -> Json:
    base = ["ID-bewijs (alleen ter controle)", "Inkomensverklaring", "Bankafschriften (selectie)"]
    if regeling.lower().startswith("huur"):
        base = ["Huurcontract", "Bewijs van huurbetaling", "Inkomensverklaring", "Vermogensopgave"]
    if situatie.lower().startswith("samen"):
        base.append("Gezamenlijke inkomensgegevens partner")
    return {"regeling": regeling, "situatie": situatie, "documenten": base}


def risk_notes(regeling: str, jaar: int, situatie: str, loonOfVermogen: bool) -> Json:
    notes: List[str] = []
    if loonOfVermogen:
        notes.append("Uw inkomen ligt dicht bij de grens (demo-indicator).")
    if situatie.lower().startswith("alleen"):
        notes.append("Controleer of u op het juiste adres staat ingeschreven.")
    if regeling.lower().startswith("huur"):
        notes.append("Controle op huurcontract en huurprijs kan nodig zijn.")
    notes.append("Onbekende spaartegoeden kunnen invloed hebben.")
    return {"aandachtspunten": notes}


def extract_entities(text: str) -> Json:
    # Heuristisch: datum, bedrag, onderwerp
    date_match = re.search(r"(\d{1,2}\s+[a-zA-Z]+\s+\d{4})", text)
    euro_match = re.search(r"€\s?([0-9\.,]+)", text)
    onderwerp = "Bezwaar"
    if "naheffing" in text.lower():
        onderwerp = "Bezwaar tegen naheffing"
    return {
        "datum": date_match.group(1) if date_match else "15 januari 2024",
        "bedrag": f"€{euro_match.group(1)}" if euro_match else "€750",
        "onderwerp": onderwerp,
    }


def classify_case(text: str) -> Json:
    t = text.lower()
    if "inkomen" in t or "te laag" in t:
        return {"type": "Inkomensbezwaar", "reden": "Hoogte van aanslag"}
    if "termijn" in t or "te laat" in t:
        return {"type": "Termijnbezwaar", "reden": "Ontvankelijkheid/termijn"}
    return {"type": "Algemeen bezwaar", "reden": "Onvoldoende onderbouwing (demo)"}


def policy_snippets(type: str) -> Json:
    # Dummy snippets, not real policy.
    if type == "Inkomensbezwaar":
        snippets = [
            "Beoordeel het relevante inkomensjaar en eventuele mutaties (demo).",
            "Controleer bewijsstukken en inkomensgegevens (demo).",
        ]
    else:
        snippets = [
            "Controleer of het bezwaar ontvankelijk is (termijn, belanghebbende) (demo).",
            "Vraag ontbrekende stukken op indien nodig (demo).",
        ]
    return {"type": type, "snippets": snippets}
