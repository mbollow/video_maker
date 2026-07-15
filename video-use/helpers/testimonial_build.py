"""Testimonial Phase 2: interview.txt -> fertiges Video -> Freigabe-Ordner.

  1. interview.txt + testimonial.json lesen
  2. pro Block die Keep-Ranges rechnen (Video sanft) und die Untertitel bereinigen (Text sauber)
  3. Intro-/Fragen-/Fazit-/Outro-Folien rendern
  4. Clips bauen (Marken-Rahmen + Logo + eingebrannte Untertitel) und zusammensetzen
  5. Selbstcheck (aac-Tonspur + plausible Dauer) — Pflicht vor dem Deploy
  6. Auto-Push in den Freigabe-Ordner als naechste Version (final_vN+1)

Usage:
    uv run --project ./video-use python ./video-use/helpers/testimonial_build.py \
        --projekt testimonial-mustermann [--no-push] [--nur-plan]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import testimonial_common as tc  # noqa: E402
from freigabe_push import DEFAULT_FREIGABE_DIR, FREIGABE_TEMPLATE  # noqa: E402

# Untertitel: dunkles Marken-Blau auf dem cremefarbenen Streifen unter dem Sprecher-Band.
# Achtung: MarginL/R/V zaehlen in der libass-Skriptaufloesung (klein!), nicht in Pixeln.
SUB_STYLE = ("FontName=Helvetica,FontSize=15,Bold=1,PrimaryColour=&H00671D28,"
             "OutlineColour=&H00F2F6F8,BackColour=&H00F2F6F8,BorderStyle=1,Outline=1.2,"
             "Shadow=0,Alignment=2,MarginV=34,MarginL=40,MarginR=40")


def slugify(text: str, max_len: int = 48) -> str:
    text = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, b)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_len].rstrip("-")


def plan(projekt: str) -> tuple[dict, list[dict]]:
    cfg = tc.load_config(projekt)
    proj = tc.project_dir(projekt)
    blocks = tc.parse_interview(proj / "interview.txt")
    data = json.loads((proj / "transcripts" / "source.json").read_text())
    words = [w for w in data["words"] if w.get("type") == "word"]

    gast = cfg["sprecher"]["gast"]
    default_gap = cfg["schnitt"]["max_pause_s"]
    exceptions = cfg["schnitt"].get("ausnahmen", {})
    fixes = cfg.get("textfixes", [])
    spellings = {k.lower(): v for k, v in cfg.get("schreibweisen", {}).items()}

    planned = []
    for b in blocks:
        name = b["block"]
        kind = name.split()[0].lower()
        if kind in ("intro", "outro"):
            planned.append({**b, "kind": kind})
            continue
        # Video-Bloecke: quelle (beliebiger Sprecher) oder antwort (nur Gast)
        field = b.get("antwort") or b.get("quelle")
        if not field:
            continue
        windows = tc.parse_ranges_field(field)
        speaker = gast if b.get("antwort") else None
        ws = tc.words_in(words, windows, speaker=speaker)
        if not ws:
            print(f"  [warn] Block [{name}]: keine Woerter im Bereich {field} — uebersprungen")
            continue
        gap = float(exceptions.get(name, default_gap))
        ranges = tc.build_ranges(ws, gap)
        tokens = tc.clean_tokens(ws, fixes, spellings)
        planned.append({**b, "kind": kind, "ranges": ranges, "tokens": tokens,
                        "dur": round(sum(r[1] - r[0] for r in ranges), 2)})
    return cfg, planned


def render_cards(projekt: str, cfg: dict, planned: list[dict]) -> None:
    proj = tc.project_dir(projekt)
    brand = tc.REPO_ROOT / "brand-guidelines" / cfg["brand"]
    intro = next((b for b in planned if b["kind"] == "intro"), {})
    # Eyebrow der Fragen-Folien: ueber alle Karten identisch (kommt aus dem [intro]-Block).
    eyebrow = intro.get("karten_eyebrow") or intro.get("eyebrow") or "Kundenstimme"
    for b in planned:
        k, name = b["kind"], b["block"]
        png = proj / "cards" / f"{slugify(name)}.png"
        if k == "intro":
            html = tc.card_html(brand, "intro", {
                "eyebrow": b.get("eyebrow", "Kundenstimme"), "name": b.get("name", ""),
                "rolle": b.get("rolle", ""), "meta": b.get("meta", "")})
        elif k == "outro":
            html = tc.card_html(brand, "outro", {
                "eyebrow": b.get("eyebrow", ""),
                "text": tc.emphasise(b.get("text", ""), b.get("highlight")),
                "cta": b.get("cta", ""),
                "url": tc.emphasise(b.get("url", ""), "/" + b.get("url", "").split("/", 1)[-1]
                                    if "/" in b.get("url", "") else None)})
        elif k in ("frage", "fazit") and b.get("text"):
            m = re.search(r"(\d+)", name)
            pill = b.get("pill") or (f"Frage {int(m.group(1)):02d}" if m else name.title())
            plain = b["text"]
            html = tc.card_html(brand, "frage", {
                "eyebrow": b.get("card_eyebrow", eyebrow), "pill": pill,
                "cls": "qsmall" if len(plain) > 78 else "",
                "text": tc.emphasise(plain, b.get("highlight"))})
        else:
            continue
        tc.render_card(html, png)
        b["card"] = png


def build(projekt: str, push: bool = True) -> Path:
    cfg, planned = plan(projekt)
    proj = tc.project_dir(projekt)
    src = proj / cfg["quelle"]
    logo = tc.REPO_ROOT / "brand-guidelines" / cfg["brand"] / "assets/logo-color.png"
    band, bg = cfg["band"], cfg["hintergrund"]
    kd = cfg["karten"]

    render_cards(projekt, cfg, planned)

    clips: list[Path] = []
    expected = 0.0
    for b in planned:
        k, name = b["kind"], b["block"]
        slug = slugify(name)
        if b.get("card") is not None:
            dur = kd["intro_s"] if k == "intro" else kd["outro_s"] if k == "outro" else kd["frage_s"]
            c = tc.build_card_clip(b["card"], proj / "work" / f"card_{slug}.mp4", dur,
                                   fade_in=(k == "intro"), fade_out=(k == "outro"))
            clips.append(c)
            expected += dur
        if b.get("ranges"):
            srt = proj / "work" / f"{slug}.srt"
            srt.write_text(tc.build_srt(b["ranges"], b["tokens"]))
            c = tc.build_clip(src, logo, b["ranges"], srt, band, bg, SUB_STYLE,
                              proj / "work" / f"{slug}.mp4")
            clips.append(c)
            expected += b["dur"]
            cuts = len(b["ranges"]) - 1
            print(f"  [build] {name:14s} {b['dur']:6.1f}s  {cuts} Schnitt(e)")

    version = next_version(projekt, cfg)
    out = proj / "renders" / f"testimonial_v{version}.mp4"
    tc.concat(clips, out)

    problems = tc.selfcheck(out, expected)
    if problems:
        print("\n  [SELBSTCHECK FEHLGESCHLAGEN]")
        for p in problems:
            print("   -", p)
        sys.exit(1)
    info = tc.probe(out)
    print(f"\n  [ok] {out}  ({info['duration']:.1f}s, {info['codecs']})")

    if push:
        push_freigabe(projekt, cfg, out, version)
    return out


def freigabe_folder(cfg: dict) -> Path:
    base = Path(cfg.get("freigabe_dir") or DEFAULT_FREIGABE_DIR)
    return base


def next_version(projekt: str, cfg: dict) -> int:
    """Bestehende Renders NIE ueberschreiben — immer die naechste Version.

    Zaehlt BEIDE Seiten: die lokalen Renders und die schon im Freigabe-Ordner
    liegenden final_vN. Sonst startet ein frisch aufgesetztes Projekt wieder bei
    v1 und wuerde eine bereits verschickte Version ueberschreiben.
    """
    n = 0
    for p in (tc.project_dir(projekt) / "renders").glob("*_v*.mp4"):
        m = re.search(r"_v(\d+)\.mp4$", p.name)
        if m:
            n = max(n, int(m.group(1)))
    folder = cfg.get("freigabe_folder")
    if folder:
        fdir = freigabe_folder(cfg) / folder
        if fdir.exists():
            for p in fdir.glob("final_v*.mp4"):
                m = re.match(r"final_v(\d+)__", p.name)
                if m:
                    n = max(n, int(m.group(1)))
    return n + 1


def push_freigabe(projekt: str, cfg: dict, video: Path, version: int) -> None:
    base = freigabe_folder(cfg)
    if not base.exists():
        print(f"  [push] Freigabe-Ordner nicht gefunden: {base} — uebersprungen.")
        return
    folder_name = cfg.get("freigabe_folder")
    if not folder_name:
        nums = [int(p.name[:3]) for p in base.iterdir() if p.is_dir() and p.name[:3].isdigit()]
        folder_name = f"{(max(nums) + 1) if nums else 1:03d}_{slugify(projekt)}"
        cfg["freigabe_folder"] = folder_name
        tc.save_config(projekt, cfg)
    folder = base / folder_name
    folder.mkdir(parents=True, exist_ok=True)

    titel = slugify(projekt)
    dest = folder / f"final_v{version}__{titel}.mp4"
    shutil.copy2(video, dest)

    fb = folder / f"FREIGABE__{titel}.txt"
    if not fb.exists():   # nie ueberschreiben — da stehen die Rueckmeldungen drin
        fb.write_text(FREIGABE_TEMPLATE +
                      f"Testimonial — {projekt}\n"
                      "Langform fuer Website-Embed (16:9, mit eingebrannten Untertiteln).\n\n"
                      "Aufbau: Intro-Folie -> (Fragen-Folie -> Antwort) ... -> Outro mit CTA.\n"
                      "Das Video ist bewusst kaum geschnitten; bereinigt wurden nur die Untertitel.\n")
    print(f"  [push] {dest}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Testimonial Phase 2 — bauen + Freigabe-Push")
    ap.add_argument("--projekt", required=True)
    ap.add_argument("--no-push", action="store_true", help="Notausgang: nicht in die Freigabe kopieren")
    ap.add_argument("--nur-plan", action="store_true", help="nur Schnitt/Untertitel zeigen, nichts rendern")
    args = ap.parse_args()

    if args.nur_plan:
        _, planned = plan(args.projekt)
        for b in planned:
            if b.get("ranges"):
                print(f"\n### {b['block']}  {b['dur']}s  {len(b['ranges']) - 1} Schnitt(e)  {b['ranges']}")
                print("   ", " ".join(t["t"] for t in b["tokens"]))
        return
    build(args.projekt, push=not args.no_push)


if __name__ == "__main__":
    main()
