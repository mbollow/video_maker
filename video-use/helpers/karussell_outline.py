"""Phase 1 of the Karussell pipeline: generate a full carousel outline.

Calls the Anthropic API once with the brand voice and a theme, and writes an
editable outline.txt to image-carousels/<batch>/. The user/Juliana then curate
it (strike/rewrite/reorder slides) before Phase 2 (`karussell:build`) renders it.

A carousel is a narrative arc, e.g. Problem → Kosten → Reframe → … → eine Frage,
framed by a start slide (hook + photo) and an end slide (statement + CTA).

Usage:
    npm run karussell:outline -- --batch recency-effekt --thema "Der Recency Effekt"
    python helpers/karussell_outline.py --batch <name> --thema "..." --slides 6
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import karussell_common as kc  # noqa: E402
import bild_common as bc  # noqa: E402
from bild_hooks import read_brand_voice  # noqa: E402
from caption_gen import call_anthropic, extract_json  # noqa: E402
from transcribe import _load_env_key  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-4-6"
PHOTO_VOCAB = sorted(set(bc.TOPIC_MAP.keys()))


def available_icons() -> list[str]:
    return sorted(p.stem for p in kc.ICONS_DIR.glob("*.svg"))


def build_prompt(brand_voice: str, thema: str, slides: int | None,
                 icons: list[str], provokativ: bool) -> str:
    count_line = (
        f"Erzeuge GENAU {slides} Innen-Slides."
        if slides else
        "Erzeuge 5 oder 6 Innen-Slides (wähle die Anzahl passend zum Erzählbogen)."
    )
    prov = (
        "\nTon DIESE Runde deutlich zugespitzter/provokanter — unbequem, aber "
        "respektvoll und mit konstruktivem Kern.\n" if provokativ else ""
    )
    return f"""Du entwirfst einen **Karussell-Post** (mehrteilige Bildstrecke, Instagram/LinkedIn)
der Marke Palstek (Führungskräfte-Coaching, DACH). Durchgehend **Du-Ansprache**, nie „Sie".

THEMA des Karussells: {thema}

Ein Karussell erzählt einen Bogen über mehrere Slides:
- **start**: Titel-Slide. Ein knackiger, leicht provokanter HOOK (max ~9 Wörter), der zum
  Weiterwischen reizt. Dazu 1-2 `highlight`-Wörter (exakter Wortlaut aus dem Hook) für die
  Marker-Box.
- **Innen-Slides**: {count_line} Jeder hat einen kurzen, dachziegelartigen TITEL (2-4 Wörter),
  ein passendes Line-ICON und 2-4 kurze Fließtext-Absätze (`text`). Absätze mit Leerzeile
  trennen; innerhalb eines Absatzes mit Zeilenumbrüchen (\\n) für Rhythmus.
  WICHTIG zum Layout: Die Schrift ist groß und die Spalte schmal — jede EINZELNE Zeile
  (zwischen zwei \\n) darf **maximal ~5 Wörter / ~32 Zeichen** lang sein, damit sie nicht
  unschön umbricht. Lieber öfter umbrechen. Halte jeden Innen-Slide insgesamt knapp
  (Richtwert ≤ ~55 Wörter), sonst läuft der Text unten aus dem Bild.
  Der Bogen sollte tragen, z.B.: das eigentliche Problem → was es kostet → der Reframe →
  konkrete Einsicht → Mini-Praxis → die eine Frage. Optional 1-2 `highlight`-Wörter je Slide.
- **end**: Schluss-Statement (1-2 Sätze, verdichtet die Kernbotschaft) + Marker-`highlight` +
  ein handschriftlicher `cta` (Standard: „Folge mir, wenn du deine Führung bewusst gestalten willst.").

Für Foto-/Icon-Auswahl gib je Slide 1-3 `thema`-Stichwörter.
- start & end: bevorzugt aus dieser Foto-Liste: {", ".join(PHOTO_VOCAB)}.
- Innen-`icon`: WÄHLE einen Namen AUS DIESER LISTE (exakt so schreiben):
{", ".join(icons)}.
{prov}
Regeln: keine Buzzwords/Marketing-Sprech; jede Aussage steht für sich; erfinde keine Fakten.

## MARKEN-STIMME (Ground-Truth für Ton & Wording)
{brand_voice}

## OUTPUT — reines JSON, kein Markdown-Fence, kein Kommentar:
{{"thema": "{thema}",
  "eyebrow": "<kurzer Eyebrow, meist = thema>",
  "start": {{"hook": "...", "highlight": ["..."], "thema": ["fuehrung"]}},
  "slides": [
    {{"titel": "...", "icon": "brain", "highlight": ["..."], "thema": ["denken"],
      "text": "Absatz eins.\\nZweite Zeile.\\n\\nAbsatz zwei."}}
  ],
  "end": {{"statement": "...", "highlight": ["..."],
           "cta": "Folge mir, wenn du deine Führung bewusst gestalten willst.",
           "thema": ["fuehrung"]}}}}
"""


def to_carousel(data: dict) -> dict:
    slides: list[dict] = []
    start = data.get("start") or {}
    slides.append({"kind": "start", "hook": start.get("hook", ""),
                   "highlight": start.get("highlight", []), "bild": "juliana",
                   "thema": start.get("thema", [])})
    for i, s in enumerate(data.get("slides") or [], start=1):
        slides.append({"kind": "inner", "seq": f"{i:02d}", "titel": s.get("titel", ""),
                       "icon": s.get("icon", ""), "highlight": s.get("highlight", []),
                       "thema": s.get("thema", []), "text": s.get("text", "")})
    end = data.get("end") or {}
    slides.append({"kind": "end", "statement": end.get("statement", ""),
                   "highlight": end.get("highlight", []),
                   "cta": end.get("cta", "Folge mir, wenn du deine Führung bewusst gestalten willst."),
                   "bild": "juliana", "thema": end.get("thema", [])})
    return {"thema": data.get("thema", ""),
            "eyebrow": data.get("eyebrow") or data.get("thema", ""),
            "slides": slides}


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a curatable carousel outline")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--thema", required=True, help="Thema des Karussells")
    ap.add_argument("--slides", type=int, default=None, help="Feste Innen-Slide-Anzahl (sonst 5-6)")
    ap.add_argument("--brand", default="default")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--provokativ", action="store_true")
    ap.add_argument("--force", action="store_true", help="outline.txt überschreiben")
    args = ap.parse_args()

    out_path = kc.CAROUSELS_ROOT / args.batch / "outline.txt"
    if out_path.exists() and not args.force:
        sys.exit(f"outline.txt existiert schon: {out_path}\n--force zum Neugenerieren (überschreibt!).")

    brand_voice = read_brand_voice(args.brand)
    api_key = _load_env_key("ANTHROPIC_API_KEY")
    icons = available_icons()

    tone = " (provokant)" if args.provokativ else ""
    print(f"Generiere Karussell-Entwurf „{args.thema}\"{tone} (model={args.model}) ...")
    prompt = build_prompt(brand_voice, args.thema, args.slides, icons, args.provokativ)
    data = extract_json(call_anthropic(prompt, model=args.model, api_key=api_key, max_tokens=4000))
    carousel = to_carousel(data)
    if not carousel["slides"]:
        sys.exit("Kein Entwurf erhalten. Nochmal versuchen?")

    kc.write_outline(out_path, args.batch, carousel)
    n_inner = sum(1 for s in carousel["slides"] if s["kind"] == "inner")
    print(f"\nEntwurf geschrieben ({n_inner} Innen-Slides) → {out_path.relative_to(kc.REPO_ROOT)}")
    print("\nNächster Schritt:")
    print("  1) outline.txt öffnen, kuratieren (Slides umschreiben/streichen/ergänzen, Icons/highlight prüfen)")
    print(f"  2) npm run karussell:build -- --batch {args.batch}")


if __name__ == "__main__":
    main()
