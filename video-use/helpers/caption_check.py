#!/usr/bin/env python3
"""Caption-Vorpruefung — laeuft VOR jedem Upload zu GoHighLevel.

Warum: Captions werden per LLM erzeugt und danach von Hand nachgezogen. Beim
Karussell 002 standen vier Fehler im freigegebenen Text ("laeuft trotzdem
laeuft", ein abgebrochener Satz, "kokreten SItuation", "einen einen Termin").
Rausgegangen waere das unbemerkt. Seitdem gilt: erst pruefen, Fundstellen dem
Nutzer nennen, Freigabe abwarten — dann hochladen.

Die Pruefungen hier sind bewusst mechanisch und falsch-positiv-arm. Sie
ERSETZEN nicht das Lesen: Sinn, Tonfall und Sachfehler faellt kein Regex auf.
Sie sind das Netz darunter.

    npm run caption:check                    # alle FREIGEGEBEN-Ordner
    npm run caption:check -- --only 002_     # nur ein Ordner
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from freigabe_push import DEFAULT_FREIGABE_DIR  # noqa: E402
from ghl_sync_captions import newest_caption_file  # noqa: E402

SM_BASE = Path(DEFAULT_FREIGABE_DIR).parent
AREAS = ["Freigabeprozess – Video", "Freigabeprozess – Bilder",
         "Freigabeprozess – Karussell", "Freigabeprozess - Testimonial"]

# Abkuerzungen, die legitim auf einen Punkt enden.
_ABBR = {"z.B", "u.a", "d.h", "bzw", "ca", "usw", "etc", "inkl", "ggf", "Nr", "Dr", "Abs"}


def _lines(text: str) -> list[tuple[int, str]]:
    return [(i + 1, ln) for i, ln in enumerate(text.splitlines())]


def check(text: str) -> list[str]:
    """Mechanische Fundstellen als lesbare Zeilen zurueckgeben."""
    out: list[str] = []
    body = re.sub(r"^=+$|^(LINKEDIN|INSTAGRAM|TIKTOK|YOUTUBE)$", "", text, flags=re.M)

    for n, ln in _lines(body):
        s = ln.strip()
        if not s:
            continue

        # 1) Direkt doppeltes Wort ("einen einen").
        doppelt = set()
        for m in re.finditer(r"\b(\w{2,})\s+\1\b", s, re.IGNORECASE):
            doppelt.add(m.group(1).lower())
            out.append(f"Z{n}: doppeltes Wort „{m.group(1)} {m.group(1)}“")

        # 2) Dasselbe laengere Wort zweimal im selben Satz — typischer Rest vom
        #    Umformulieren ("laeuft trotzdem laeuft es nicht rund").
        for teil in re.split(r"[.!?;]", s):
            woerter = [w.lower() for w in re.findall(r"\b\w{5,}\b", teil)]
            for w in sorted(set(woerter)):
                if woerter.count(w) > 1 and w not in doppelt and w not in (
                        "teams", "team", "mitarbeiter", "mitarbeitende"):
                    out.append(f"Z{n}: „{w}“ steht zweimal im selben Satz")

        # 3) Grossbuchstabe mitten im Wort ("SItuation"). Hashtags ausnehmen —
        #    dort ist CamelCase gewollt (#PalstekGmbH, #FührungImKMU).
        ohne_tags = re.sub(r"#\w+|https?://\S+", " ", s)
        for m in re.finditer(r"\b\w{3,}\b", ohne_tags):
            w = m.group(0)
            if w.isupper() or w.islower():          # KMU / DM bzw. normale Woerter
                continue
            if any(c.isupper() for c in w[1:]):     # Grossbuchstabe NACH dem ersten
                out.append(f"Z{n}: seltsame Schreibweise „{w}“")

        # 4) Satz endet auf Komma -> abgebrochen.
        if s.endswith(","):
            out.append(f"Z{n}: Satz endet auf ein Komma — abgebrochen?")

        # 5) Leerzeichen vor Satzzeichen / doppelte Leerzeichen.
        if re.search(r"\s+[,.!?]", s):
            out.append(f"Z{n}: Leerzeichen vor einem Satzzeichen")
        if "  " in s:
            out.append(f"Z{n}: doppeltes Leerzeichen")

        # 6) Letztes Wort vor dem Punkt sieht abgeschnitten aus
        #    ("… per DM, Komment.") — kurzes Wort, kein Hashtag, keine Abkuerzung.
        m = re.search(r"[,;]\s+(\w{4,10})\.\s*$", s)
        if m and m.group(1) not in _ABBR and not m.group(1)[0].isupper() is False:
            out.append(f"Z{n}: „{m.group(1)}.“ wirkt abgeschnitten")

        # 7) Termin-CTA abseits des Standards „Erstgespräch vereinbaren".
        #    Bewusst nur MELDEN, nicht ersetzen: der Satz drumherum muss mit
        #    umformuliert werden, das ist Textarbeit und keine Ersetzung.
        for m in re.finditer(r"\b(Beratungstermin\w*|Beratungsgespräch\w*|kostenlos\w*|"
                             r"gratis|unverbindlich\w*|Termin buchen|[Bb]uch(e|t)? dir\b|"
                             r"[Bb]uch dein\w*)", s):
            out.append(f"Z{n}: „{m.group(0)}“ — CTA-Standard ist "
                       f"„Erstgespräch vereinbaren“ ohne Preis-Zusatz")

    # 8) Doppelte Hashtags — je Plattform-Block, denn LinkedIn und Instagram
    #    duerfen selbstverstaendlich dieselben Tags fuehren.
    for block in re.split(r"^(?:LINKEDIN|INSTAGRAM|TIKTOK|YOUTUBE)$", text, flags=re.M)[1:]:
        tags = re.findall(r"#\w+", block)
        for t in sorted(set(tags)):
            if tags.count(t) > 1:
                out.append(f"Hashtag {t} steht im selben Block {tags.count(t)}x")

    seen: list[str] = []
    for o in out:                       # Reihenfolge halten, Dubletten raus
        if o not in seen:
            seen.append(o)
    return seen


def check_folder(folder: Path) -> list[str]:
    """Neueste captions*.txt eines Freigabe-Ordners pruefen."""
    newest = newest_caption_file(folder)
    if not newest:
        return []
    found = check(newest.read_text(encoding="utf-8"))
    return [f"{newest.name}: {f}" for f in found]


def main() -> None:
    ap = argparse.ArgumentParser(description="Captions vor dem Upload pruefen")
    ap.add_argument("--only", help="Nur Ordner, deren Name diesen Text enthaelt")
    args = ap.parse_args()

    total = 0
    for area in AREAS:
        a = SM_BASE / area
        if not a.exists():
            continue
        for folder in sorted(p for p in a.iterdir() if p.is_dir()):
            if folder.name in ("veröffentlicht", "archiv"):
                continue
            if args.only and args.only.lower() not in folder.name.lower():
                continue
            fr = next(iter(folder.glob("FREIGABE*.txt")), None)
            if not fr or "FREIGEGEBEN" not in fr.read_text(encoding="utf-8").splitlines()[0]:
                continue
            found = check_folder(folder)
            if found:
                total += len(found)
                print(f"\n{folder.name}")
                for f in found:
                    print(f"   • {f}")

    if total:
        print(f"\n{total} Fundstelle(n). Dem Nutzer nennen und Freigabe abwarten, "
              f"BEVOR hochgeladen wird.")
    else:
        print("Keine mechanischen Auffaelligkeiten. Trotzdem selbst gegenlesen — "
              "Sinn und Sachfehler sieht kein Regex.")


if __name__ == "__main__":
    main()
