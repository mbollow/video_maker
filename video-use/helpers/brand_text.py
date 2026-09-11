#!/usr/bin/env python3
"""Marken-Textregeln, die fuer JEDES Format gelten — Video, Bild, Karussell.

Reine Nachbearbeitung, bewusst deterministisch: Captions entstehen per LLM, und
eine Regel, die nur im Prompt steht, faellt frueher oder spaeter wieder raus.
Was hier drin steht, greift danach in jedem Fall.

Zwei Regeln:

**1. Brand-Hashtag = `#PalstekGmbH`, nie `#Palstek`.**
Der kurze Tag ist auf den Plattformen nicht der Kanal der Firma — Beitraege damit
laufen ins Leere. Betrifft alle Netzwerke und alle Formate.

**2. Eigennamen richtig schreiben: `Juliana Wiechert`, `Palstek GmbH`.**
Der eigene Nachname und der Firmenname sind die zwei Woerter, die in JEDEM Video
und JEDER Caption vorkommen koennen — und genau die verhoeren die Transkriptions-
Dienste zuverlaessig ("Wichert", "Wichard", "Palsteck"). Bis Video 016 stand
"Frau Wichert" eingebrannt im Untertitel. Ein falsch geschriebener Nachname faellt
jedem auf, der die Person kennt, und er faellt erst auf, wenn das Video fertig ist.
Deshalb steht die Tabelle hier zentral und nicht pro Projekt: sie gilt fuer
Untertitel, Captions, Folien und Thumbnails gleichermassen.
"""
from __future__ import annotations

import re

# `#Palstek` in beliebiger Schreibweise, aber NICHT wenn schon etwas folgt
# (#PalstekGmbH, #PalstekTeam ...). Ausgabe immer in der kanonischen Schreibung.
_BRAND_TAG = re.compile(r"#palstek(?![0-9A-Za-zÄÖÜäöüß_])", re.IGNORECASE)
BRAND_TAG = "#PalstekGmbH"

# ---------------------------------------------------------------------------
# Eigennamen — zentrale Schreibweisen-Tabelle
# ---------------------------------------------------------------------------
# Schluessel: kleingeschrieben, ohne Satzzeichen (so, wie `apply_spellings` und
# `norm()` in testimonial_common.py ein Token normalisieren). Wert: die korrekte
# Schreibweise. Neue Verhoerer einfach hier ergaenzen — sie wirken dann sofort in
# Untertiteln (render.build_master_srt, testimonial_build) und Captions.
NAMEN: dict[str, str] = {
    # Juliana Wiechert — Geschaeftsfuehrerin, spricht in allen Reels
    "wichert": "Wiechert",
    "wiechardt": "Wiechert",
    "wichardt": "Wiechert",
    "wichard": "Wiechert",
    "wiehert": "Wiechert",
    "juliane": "Juliana",
    # Palstek GmbH — Firmenname
    "palsteck": "Palstek",
    "pahlstek": "Palstek",
    "pahlsteck": "Palstek",
}

# Mehrwort-Schreibweisen fuer Fliesstext (Captions, Folien). Der Untertitel-Weg
# laeuft ueber NAMEN, weil dort Wort fuer Wort mit eigenen Zeiten ersetzt wird.
_TEXT_FIXES = [
    (re.compile(r"\bPalstek\s+Gmbh\b"), "Palstek GmbH"),
    (re.compile(r"\bPalstek\s+gmbh\b"), "Palstek GmbH"),
]


def fix_names(text: str) -> str:
    """Eigennamen in einem Fliesstext auf die Marken-Schreibweise bringen."""
    if not text:
        return text

    def _wort(m: "re.Match") -> str:
        roh = m.group(0)
        return NAMEN.get(roh.lower(), roh)

    # Hashtags bleiben unangetastet — dafuer ist `fix_hashtags` zustaendig.
    text = re.sub(r"(?<![#0-9A-Za-zÄÖÜäöüß])[0-9A-Za-zÄÖÜäöüß]+", _wort, text)
    for muster, ersatz in _TEXT_FIXES:
        text = muster.sub(ersatz, text)
    return text


def spellings(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Schreibweisen-Tabelle fuer `testimonial_common.clean_tokens`.

    Zentrale Eigennamen plus optional die projekt-eigenen aus `edl.json` /
    `testimonial.json` — das Projekt gewinnt, damit ein Kundenname einen
    Marken-Eintrag ueberschreiben kann.
    """
    out = dict(NAMEN)
    for k, v in (extra or {}).items():
        out[k.lower()] = v
    return out


def fix_hashtags(text: str) -> str:
    """Marken-Hashtag + Eigennamen in einem Caption-Text normalisieren."""
    if not text:
        return text
    return fix_names(_BRAND_TAG.sub(BRAND_TAG, text))


def fix_hashtag_list(tags: list | None) -> list:
    """Gleiche Regel auf eine Hashtag-Liste anwenden (ohne Duplikate)."""
    if not tags:
        return tags or []
    out: list = []
    for t in tags:
        fixed = fix_hashtags(t) if isinstance(t, str) else t
        if fixed not in out:
            out.append(fixed)
    return out


def fix_post(post: dict) -> dict:
    """Caption + Hashtags eines Post-Datensatzes in place normalisieren."""
    if not isinstance(post, dict):
        return post
    for key in ("caption", "text", "title"):
        if isinstance(post.get(key), str):
            post[key] = fix_hashtags(post[key])
    if isinstance(post.get("hashtags"), list):
        post["hashtags"] = fix_hashtag_list(post["hashtags"])
    return post
