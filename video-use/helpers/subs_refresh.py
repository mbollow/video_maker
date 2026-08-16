#!/usr/bin/env python3
"""subs_refresh.py — Untertitel einer fertigen Composition neu aus dem Transkript ziehen.

Die Reel-Compositions tragen ihre Cues als JSON-Array INLINE im `index.html`
(`const cues = [[start, end, "Text"], …]`). Wird die Untertitel-Logik in
`render.build_master_srt` verbessert, sind die bereits gebauten Compositions davon
nicht betroffen — sie behalten den Text von damals. Genau so sind Reels mit
Untertiteln ganz ohne Satzzeichen entstanden.

Dieses Werkzeug baut `master.srt` mit der AKTUELLEN Logik neu und ersetzt damit die
Cues in der Composition. Danach muss die Composition neu gerendert werden:

    npx hyperframes render projects/<projekt>/compositions \
      -o projects/<projekt>/renders/final_reel_vN.mp4 --quality standard

    python video-use/helpers/subs_refresh.py --projekt <projekt>          # Vorschau
    python video-use/helpers/subs_refresh.py --projekt <projekt> --apply  # schreiben
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import render  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CUES_RE = re.compile(r"(const cues = )(\[.*?\])(;)", re.S)


def srt_zu_cues(srt: Path) -> list:
    def sek(ts: str) -> float:
        h, m, rest = ts.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    cues = []
    for block in re.split(r"\n\s*\n", srt.read_text(encoding="utf-8").strip()):
        zeilen = block.strip().splitlines()
        if len(zeilen) < 3 or "-->" not in zeilen[1]:
            continue
        a, b = [x.strip() for x in zeilen[1].split("-->")]
        text = " ".join(z.strip() for z in zeilen[2:]).strip()
        cues.append([round(sek(a), 2), round(sek(b), 2), text])
    return cues


def main() -> None:
    ap = argparse.ArgumentParser(description="Untertitel-Cues einer Composition auffrischen")
    ap.add_argument("--projekt", required=True, help="Ordnername unter projects/")
    ap.add_argument("--apply", action="store_true", help="schreiben (Default: nur Vorschau)")
    args = ap.parse_args()

    proj = REPO / "projects" / args.projekt
    comp = proj / "compositions" / "index.html"
    edl = proj / "edl.json"
    for p in (comp, edl):
        if not p.exists():
            sys.exit(f"  [fehler] nicht gefunden: {p}")

    srt = proj / "master.srt"
    render.build_master_srt(json.loads(edl.read_text()), proj, srt, clean=True)
    neu = srt_zu_cues(srt)

    html = comp.read_text(encoding="utf-8")
    m = CUES_RE.search(html)
    if not m:
        sys.exit("  [fehler] kein `const cues = [...]` in der Composition gefunden")
    alt = json.loads(m.group(2))

    geaendert = [(a, b) for a, b in zip([c[2] for c in alt], [c[2] for c in neu]) if a != b]
    print(f"  Cues: {len(alt)} → {len(neu)}, {len(geaendert)} Texte geändert")
    for a, b in geaendert[:8]:
        print(f"    - {a}\n    + {b}")
    if len(geaendert) > 8:
        print(f"    … und {len(geaendert) - 8} weitere")

    if not args.apply:
        print("  (Vorschau — mit --apply schreiben)")
        return

    inline = "[" + ",".join(
        "[%.2f,%.2f,%s]" % (c[0], c[1], json.dumps(c[2], ensure_ascii=False)) for c in neu
    ) + "]"
    comp.write_text(html[:m.start(2)] + inline + html[m.end(2):], encoding="utf-8")
    print(f"  [ok] {comp}")
    print("  Jetzt neu rendern (npx hyperframes render …), dann Cover + Freigabe-Push.")


if __name__ == "__main__":
    main()
