#!/usr/bin/env python3
"""Testimonial — Textbausteine fuer den Praxisbericht als Word-Datei.

Der Praxisbericht (einseitiges Layout „Aus der Praxis …", vgl. Praxisbericht_WAPA.pdf /
Praxisbericht_Revision_Nord.pdf im Testimonial-Freigabe-Ordner) wird von einer
Mitarbeiterin in Canva gesetzt. Hier entstehen nur die Textbausteine, geordnet nach
den Layout-Bloecken: Kopf, Davor, Psychologie-Box, Waehrend, In Zahlen, Zitat,
Danach (Die Geschaeftsfuehrung beobachtet), Passt zu Unternehmen, offene Punkte.

Quelle: `projects/<projekt>/praxisbericht.txt` (Bloecke `[kopf]`, `[davor]`, …;
Zeilen mit "- " sind Aufzaehlungspunkte, `**fett**` wird fett, `[ERGÄNZEN: …]`
ist ein Platzhalter fuer Fakten, die im Gespraech nicht genannt wurden — die
werden rot gesetzt und am Ende gesammelt, statt geraten). Ergebnis:
`Praxisbericht_Textbausteine__<projekt>.docx` im Freigabe-Ordner (Arbeitsdokument,
wird bei erneutem Lauf ersetzt).

    npm run testimonial:praxisbericht -- --projekt testimonial-mustermann [--no-push]
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.shared import Cm, Pt, RGBColor

sys.path.insert(0, str(Path(__file__).parent))
import testimonial_common as tc  # noqa: E402
import testimonial_build as tb  # noqa: E402
from testimonial_zitate import ADRESSE, FONT, GRAU, NAVY, TEAL, _run, _shade  # noqa: E402

ROT = RGBColor(0xC0, 0x39, 0x2B)
TITEL = {
    "kopf": "Kopfzeile", "davor": "DAVOR", "psychologie": "Box: Warum Psychologinnen?",
    "waehrend": "WÄHREND", "zahlen": "IN ZAHLEN", "zitat": "Zitat (Auswahl)",
    "danach": "DANACH · Die Geschäftsführung beobachtet",
    "passt": "DAS PROGRAMM PASST ZU UNTERNEHMEN, …", "offen": "Offene Punkte vor dem Satz",
}
ORDER = ["kopf", "davor", "psychologie", "waehrend", "zahlen", "zitat", "danach", "passt", "offen"]


def parse(path: Path) -> dict[str, list[str]]:
    """Bloecke -> Zeilen (Kommentare/Leerzeilen raus; Zeilen bleiben ganz, nicht key/value)."""
    out: dict[str, list[str]] = {}
    cur = None
    for raw in path.read_text().splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^\[(.+?)\]$", line.strip())
        if m:
            cur = m.group(1).strip().lower()
            out[cur] = []
            continue
        if cur is not None:
            out[cur].append(line.strip())
    return out


def _rich(par, text: str, *, size: float = 10.5, base_bold=False) -> None:
    """**fett** und [ERGÄNZEN: …] als eigene Runs setzen."""
    for tok in re.split(r"(\*\*.+?\*\*|\[ERGÄNZEN:.*?\])", text):
        if not tok:
            continue
        if tok.startswith("**"):
            _run(par, tok[2:-2], size=size, bold=True)
        elif tok.startswith("[ERGÄNZEN"):
            _run(par, tok, size=size, bold=True, color=ROT)
        else:
            _run(par, tok, size=size, bold=base_bold)


def build(projekt: str) -> Path:
    proj = tc.project_dir(projekt)
    src = proj / "praxisbericht.txt"
    if not src.exists():
        sys.exit(f"[praxisbericht] fehlt: {src}")
    sec_map = parse(src)
    cfg = tc.load_config(projekt)
    logo = tc.REPO_ROOT / "brand-guidelines" / cfg["brand"] / tc.LOGO_DUNKEL
    kopf = dict(l.split(":", 1) for l in sec_map.get("kopf", []) if ":" in l)
    kopf = {k.strip(): v.strip() for k, v in kopf.items()}

    doc = Document()
    s = doc.sections[0]
    s.left_margin = s.right_margin = Cm(2.2)
    s.top_margin, s.bottom_margin = Cm(1.8), Cm(1.8)
    doc.styles["Normal"].font.name = FONT
    doc.styles["Normal"].font.size = Pt(10.5)

    p = doc.add_paragraph()
    _run(p, "Praxisbericht · Textbausteine", size=18, bold=True)
    if logo.exists():
        p.add_run("\t").add_picture(str(logo), height=Cm(1.2))
    p.paragraph_format.tab_stops.add_tab_stop(Cm(16.6))
    p = doc.add_paragraph()
    _run(p, f"{kopf.get('firma', projekt)}  |  {kopf.get('stand', '')}", size=10.5, bold=True)
    p = doc.add_paragraph()
    _run(p, ("Vorlage für die grafische Umsetzung in Canva, Aufbau wie die bisherigen Praxisberichte "
             "(WAPA, Revision Nord). Rot markierte Stellen sind Fakten, die im Gespräch nicht genannt "
             "wurden und vor dem Satz geklärt werden müssen. Alle Aussagen stammen aus dem "
             "Feedbackgespräch und sind sprachlich geglättet."), size=8.5, italic=True, color=GRAU)
    p.paragraph_format.space_after = Pt(12)

    platzhalter: list[str] = []
    for key in ORDER:
        lines = sec_map.get(key)
        if not lines:
            continue
        h = doc.add_paragraph()
        _run(h, TITEL[key], size=12, bold=True, color=TEAL)
        h.paragraph_format.space_before = Pt(10)
        h.paragraph_format.space_after = Pt(3)
        h.paragraph_format.keep_with_next = True

        if key == "zahlen":
            table = doc.add_table(rows=1, cols=3)
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            for i, hd in enumerate(("Zahl", "Bezeichnung", "Unterzeile")):
                c = table.rows[0].cells[i]; _shade(c, "281D67")
                _run(c.paragraphs[0], hd, size=9, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
            for l in lines:
                parts = [x.strip() for x in l.lstrip("- ").split("|")]
                parts += [""] * (3 - len(parts))
                cells = table.add_row().cells
                for i, txt in enumerate(parts[:3]):
                    _rich(cells[i].paragraphs[0], txt, size=10, base_bold=(i == 0))
            for l in lines:
                platzhalter += re.findall(r"\[ERGÄNZEN:.*?\]", l)
            continue

        for l in lines:
            platzhalter += re.findall(r"\[ERGÄNZEN:.*?\]", l)
            if key in ("kopf", "zitat") and ":" in l and not l.startswith("- "):
                k, v = l.split(":", 1)
                par = doc.add_paragraph()
                _run(par, f"{k.strip().replace('_', ' ')}: ", size=10.5, bold=True, color=GRAU)
                _rich(par, v.strip())
            elif l.startswith("- ") or key == "passt" or key == "offen":
                par = doc.add_paragraph(style="List Bullet")
                _rich(par, l[2:] if l.startswith("- ") else l)
            else:
                par = doc.add_paragraph()
                _rich(par, l)
            par.paragraph_format.space_after = Pt(4)

    f = doc.add_paragraph(); _run(f, ADRESSE, size=8, color=GRAU)
    f.paragraph_format.space_before = Pt(14)

    out_dir = proj / "praxisbericht"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"Praxisbericht_Textbausteine__{tb.slugify(projekt)}.docx"
    doc.save(out)
    print(f"  [praxisbericht] {out}  ({len(platzhalter)} Platzhalter offen)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Testimonial — Praxisbericht-Textbausteine als Word")
    ap.add_argument("--projekt", required=True)
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()
    out = build(a.projekt)
    if not a.no_push:
        from testimonial_zitate import push
        push(a.projekt, out)


if __name__ == "__main__":
    main()
