"""Phase 1 of the Bild-Post pipeline: generate hook/spruch suggestions.

Calls the Anthropic API once with the brand voice context and writes an
editable hooks.txt to image-posts/<batch>/. The user/Juliana then curates it
(strike, rewrite, add; flip status: ja/nein) before Phase 2 builds the posts.

Usage:
    npm run bild:hooks -- --batch juni-fuehrung
    python helpers/bild_hooks.py --batch <name> --count 8 --thema "Mitarbeiterbindung"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bild_common as bc  # noqa: E402
from caption_gen import call_anthropic, extract_json  # noqa: E402
from transcribe import _load_env_key  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-4-6"

THEME_VOCAB = sorted(set(bc.TOPIC_MAP.keys()))


def read_brand_voice(brand: str) -> str:
    base = bc.REPO_ROOT / "brand-guidelines" / brand
    parts = []
    for fname in ("README.md", "tone.md", "SKILL.md"):
        p = base / fname
        if p.exists():
            parts.append(f"# === {fname} ===\n{p.read_text()}")
    return "\n\n".join(parts)


def build_prompt(brand_voice: str, count: int, thema: str | None,
                 schaerfer: bool = False, avoid: list[str] | None = None) -> str:
    thema_line = f"\nThemen-Schwerpunkt für diese Runde: {thema}\n" if thema else ""
    schaerfer_line = (
        "\nDIESE RUNDE DEUTLICH PROVOKANTER: zugespitzt, reib dich an bequemen "
        "Führungs-Wahrheiten, ruhig unbequem — aber respektvoll, ohne Beleidigung "
        "oder Zynismus, und immer mit konstruktivem Kern.\n"
        if schaerfer else ""
    )
    avoid_block = ""
    if avoid:
        joined = "\n".join(f"- {a}" for a in avoid)
        avoid_block = (
            "\nVERMEIDE Wiederholungen oder Paraphrasen dieser bereits "
            f"vorhandenen Aussagen:\n{joined}\n"
        )
    return f"""Du textest On-Image-Aussagen für **Single-Image-Posts** der Marke Palstek
(Führungskräfte-Coaching, Zielgruppe: Führungskräfte im DACH-Raum).

Erzeuge genau {count} Vorschläge — eine **Mischung aus zwei Typen**:
- typ "hook":  knackig, leicht provokant, max. ~8 Wörter, soll zum Weiterlesen
               reizen. Du-Ansprache. Beispiel: "Dein Team folgt dir nicht wegen deines Titels."
- typ "spruch": zitatartig, auf den Punkt, ruhiger/weiser Ton, max. ~12 Wörter.
               Beispiel: "Führung ist nicht Kontrolle — Führung ist Klarheit."

Regeln:
- Durchgehend **Du-Ansprache** (nie "Sie").
- Keine Buzzwords ("Game-Changer", "revolutionär"), kein Marketing-Sprech.
- Jede Aussage steht für sich, ohne Kontext verständlich.
- Gib zu jeder Aussage 1-3 `thema`-Stichwörter, die zur Bildauswahl passen.
  Nutze bevorzugt aus dieser Liste: {", ".join(THEME_VOCAB)}.
{thema_line}{schaerfer_line}{avoid_block}
## MARKEN-STIMME (deine Ground-Truth für Ton & Wording)

{brand_voice}

## OUTPUT
Gib EXAKT dieses JSON-Objekt zurück, ohne Markdown-Fence, ohne Kommentar:
{{"entries": [
  {{"typ": "hook", "text": "...", "thema": ["fuehrung", "vertrauen"]}},
  {{"typ": "spruch", "text": "...", "thema": ["klarheit"]}}
]}}
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate hook/spruch suggestions for a Bild-Post batch")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--brand", default="default")
    ap.add_argument("--count", type=int, default=8)
    ap.add_argument("--thema", default=None, help="Optionaler Themen-Schwerpunkt für diese Runde")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--force", action="store_true", help="hooks.txt überschreiben, falls vorhanden")
    ap.add_argument("--append", action="store_true",
                    help="An bestehende hooks.txt anhängen (Nummerierung läuft weiter)")
    ap.add_argument("--provokativ", action="store_true",
                    help="Deutlich provokanter/zugespitzter Ton für diese Runde")
    args = ap.parse_args()

    out_path = bc.REPO_ROOT / "image-posts" / args.batch / "hooks.txt"
    if out_path.exists() and not args.force and not args.append:
        sys.exit(f"hooks.txt existiert schon: {out_path}\n"
                 f"--append zum Anhängen, oder --force zum Neugenerieren (überschreibt!).")

    brand_voice = read_brand_voice(args.brand)
    api_key = _load_env_key("ANTHROPIC_API_KEY")

    # Beim Anhängen die vorhandenen Texte mitgeben, damit nicht doppelt getextet wird.
    avoid = None
    if args.append and out_path.exists():
        avoid = [e["text"] for e in bc.parse_hooks_txt(out_path) if e.get("text")]

    prompt = build_prompt(brand_voice, args.count, args.thema,
                          schaerfer=args.provokativ, avoid=avoid)

    tone = " (provokant)" if args.provokativ else ""
    print(f"Generiere {args.count} Hook/Spruch-Vorschläge{tone} (model={args.model}) ...")
    text = call_anthropic(prompt, model=args.model, api_key=api_key, max_tokens=2000)
    data = extract_json(text)
    entries = data.get("entries") or []
    if not entries:
        sys.exit("Keine Vorschläge erhalten. Nochmal versuchen?")

    if args.append and out_path.exists():
        start = bc.append_hooks_txt(out_path, entries)
        print(f"\n{len(entries)} Vorschläge angehängt (ab Nr. {start:02d}) → {out_path.relative_to(bc.REPO_ROOT)}")
    else:
        bc.write_hooks_txt(out_path, args.batch, entries)
        print(f"\n{len(entries)} Vorschläge geschrieben → {out_path.relative_to(bc.REPO_ROOT)}")
    print("\nNächster Schritt:")
    print("  1) Datei öffnen, Hooks/Sprüche kuratieren (umschreiben, streichen, status: nein zum Auslassen)")
    print(f"  2) npm run bild:build -- --batch {args.batch}")


if __name__ == "__main__":
    main()
