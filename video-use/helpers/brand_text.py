#!/usr/bin/env python3
"""Marken-Textregeln, die fuer JEDES Format gelten — Video, Bild, Karussell.

Reine Nachbearbeitung, bewusst deterministisch: Captions entstehen per LLM, und
eine Regel, die nur im Prompt steht, faellt frueher oder spaeter wieder raus.
Was hier drin steht, greift danach in jedem Fall.

Bisher eine Regel:

**Brand-Hashtag = `#PalstekGmbH`, nie `#Palstek`.**
Der kurze Tag ist auf den Plattformen nicht der Kanal der Firma — Beitraege damit
laufen ins Leere. Betrifft alle Netzwerke und alle Formate.
"""
from __future__ import annotations

import re

# `#Palstek` in beliebiger Schreibweise, aber NICHT wenn schon etwas folgt
# (#PalstekGmbH, #PalstekTeam ...). Ausgabe immer in der kanonischen Schreibung.
_BRAND_TAG = re.compile(r"#palstek(?![0-9A-Za-zÄÖÜäöüß_])", re.IGNORECASE)
BRAND_TAG = "#PalstekGmbH"


def fix_hashtags(text: str) -> str:
    """Marken-Hashtag in einem Caption-Text normalisieren."""
    if not text:
        return text
    return _BRAND_TAG.sub(BRAND_TAG, text)


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
