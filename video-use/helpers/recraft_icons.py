"""Karussell-Icons via Recraft (Custom-Style, echtes SVG).

Erzeugt Icons im Stil der handgemachten Palstek-Icons: ein Custom-Style wurde
einmalig aus Referenz-Icons trainiert (Recraft `POST /styles`) und liegt als
`RECRAFT_ICON_STYLE_ID` in der .env. Hier generieren wir per Prompt neue Icons
in genau diesem Stil — als bearbeitbares SVG, das direkt in die Karussell-Logik
faellt (resolve_icon_svg inlined die Datei aus karussell_assets/icons/).

Warum Recraft und nicht FLUX-LoRA: Icons sind saubere Vektor-Strichgrafik; FLUX
liefert Raster ohne Transparenz. Recraft V3 Vector gibt echtes SVG zurueck und
lernt den Stil aus 5 Referenzbildern (kein Training noetig).

Ablauf:
  recraft:icon --prompt "..." --slug <name> [--count N]
    -> N Varianten nach karussell_assets/icons/<name>__i.svg (Kuration)
  recraft:icon --prompt "..." --slug <name> --count 1 --pick
    -> genau eine Datei <name>.svg (fertig zum Pinnen via `icon: <name>`)

Der weisse Recraft-Hintergrund wird zu transparent gestrippt.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transcribe import _load_env_key  # noqa: E402  (liest .env, exit bei fehlend)

HELPERS = Path(__file__).resolve().parent
ICONS_DIR = HELPERS / "karussell_assets" / "icons"
API = "https://external.api.recraft.ai/v1"


def _env(key: str, required: bool = True) -> str:
    try:
        return _load_env_key(key)
    except SystemExit:
        if required:
            raise
        return ""


def _flatten(svg: str, bg_hex: str) -> str:
    """Recraft-Weiss auf die Slide-Hintergrundfarbe setzen.

    Recraft zeichnet Linien als volle Teal-Flaechen mit WEISSEN Aussparungen
    obendrauf — das Weiss formt die Negativraeume (Innenflaechen, Zwischenraeume)
    und den Rahmen-Hintergrund. Es einfach zu entfernen wuerde die Teal-Flaeche
    freilegen (solider Klotz). Deshalb faerben wir alle near-white Fuellungen auf
    die bekannte Slide-Farbe `bg_hex` (Karussell = Creme #f8f6f2): Hintergrund und
    Aussparungen verschmelzen dann optisch mit der Slide, nur die Teal-Linien
    bleiben sichtbar. Die hellen Teal-Antialias-Kanten bleiben unangetastet.
    """
    bg_hex = bg_hex.lstrip("#")
    br, bgc, bb = int(bg_hex[0:2], 16), int(bg_hex[2:4], 16), int(bg_hex[4:6], 16)
    repl = f"fill=\"rgb({br},{bgc},{bb})\""

    def _sub(m: re.Match) -> str:
        r, g, b = (int(x) for x in m.group(1, 2, 3))
        return repl if min(r, g, b) >= 240 else m.group(0)

    return re.sub(r'fill="rgb\((\d+),\s*(\d+),\s*(\d+)\)"', _sub, svg)


def generate(prompt: str, style_id: str, token: str, bg_hex: str = "#f8f6f2",
             model: str = "recraftv3", size: str = "1024x1024",
             seed: int | None = None) -> str:
    body = {"prompt": prompt, "style_id": style_id, "model": model, "size": size}
    if seed is not None:
        body["random_seed"] = seed
    r = requests.post(f"{API}/images/generations",
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/json"},
                      json=body, timeout=120)
    if r.status_code != 200:
        sys.exit(f"Recraft-Fehler {r.status_code}: {r.text[:300]}")
    url = r.json()["data"][0]["url"]
    svg = requests.get(url, timeout=60).text
    return _flatten(svg, bg_hex)


def main() -> None:
    ap = argparse.ArgumentParser(description="Karussell-Icon via Recraft Custom-Style (SVG)")
    ap.add_argument("--prompt", required=True, help="Was das Icon zeigen soll (englisch klappt am besten)")
    ap.add_argument("--slug", required=True, help="Dateiname-Basis in karussell_assets/icons/")
    ap.add_argument("--count", type=int, default=3, help="Varianten zum Kuratieren (Default 3)")
    ap.add_argument("--pick", action="store_true",
                    help="Genau 1 Variante direkt als <slug>.svg speichern (statt <slug>__i.svg)")
    ap.add_argument("--outdir", default=str(ICONS_DIR))
    ap.add_argument("--bg", default="#f8f6f2",
                    help="Slide-Hintergrundfarbe, auf die das Recraft-Weiss gefaerbt wird (Karussell = Creme)")
    ap.add_argument("--seed-base", type=int, default=1)
    args = ap.parse_args()

    token = _env("RECRAFT_API_TOKEN")
    style_id = _env("RECRAFT_ICON_STYLE_ID")
    if not style_id:
        sys.exit("RECRAFT_ICON_STYLE_ID fehlt in .env — erst einen Custom-Style anlegen.")
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    n = 1 if args.pick else max(1, args.count)
    print(f"Recraft-Icon [{args.slug}]: {n}x  \"{args.prompt[:70]}\"")
    written = []
    for i in range(n):
        svg = generate(args.prompt, style_id, token, bg_hex=args.bg, seed=args.seed_base + i)
        if args.pick:
            dest = outdir / f"{args.slug}.svg"
        else:
            dest = outdir / f"{args.slug}__{i + 1}.svg"
        dest.write_text(svg)
        written.append(dest.name)
        print(f"  [{i + 1}/{n}] {dest.name}  ({len(svg)} B)")
        time.sleep(0.3)
    if not args.pick:
        print(f"\nKuratieren: die beste Variante in {args.slug}.svg umbenennen, dann via "
              f"`icon: {args.slug}` im outline.txt pinnen.")


if __name__ == "__main__":
    main()
