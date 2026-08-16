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
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import testimonial_common as tc  # noqa: E402
import testimonial_idbox as ti  # noqa: E402
import testimonial_thumbnail as tt  # noqa: E402
from freigabe_push import DEFAULT_TESTIMONIAL_FREIGABE_DIR, FREIGABE_TEMPLATE  # noqa: E402

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


def plan(projekt: str, zoom_experiment: bool = False) -> tuple[dict, list[dict]]:
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
    zoomcfg = cfg.get("zoom") or {}
    # Der Ken-Burns-Push auf den Gast ist bewusst KEIN Automatismus: er greift nur,
    # wenn dieser Build explizit mit --zoom als Experiment laeuft ODER die
    # testimonial.json fuer dieses Projekt zoom.enabled=true setzt (nach Freigabe).
    # Ein frisch aufgesetztes Video zoomt nie von allein — pro Video ausprobieren
    # und Feedback abwarten (Framing ist gast-/videospezifisch, z.B. Sitzposition).
    zoom_on = zoom_experiment or bool(zoomcfg.get("enabled"))
    # Technisches Minimum: rein + mind. 1 s halten + raus + Rueckfahrt-Puffer.
    # Sonst wuerde die 5-Phasen-Kurve auf kurzen Antworten zerdrueckt.
    tech_min = (float(zoomcfg.get("start_s", 5.0)) + float(zoomcfg.get("ramp_s", 2.5))
                + float(zoomcfg.get("out_ramp_s", zoomcfg.get("ramp_s", 2.5)))
                + float(zoomcfg.get("end_pad_s", 4.0)) + 1.0)
    zoom_min = max(float(zoomcfg.get("min_answer_s", 12)), tech_min)

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
        is_answer = bool(b.get("antwort"))   # Gast spricht — nur hier zoomen wir auf ihn
        speaker = gast if is_answer else None
        ws = tc.words_in(words, windows, speaker=speaker)
        if not ws:
            print(f"  [warn] Block [{name}]: keine Woerter im Bereich {field} — uebersprungen")
            continue
        gap = float(exceptions.get(name, default_gap))
        # Interviewer-Bleed verhindern: folgt direkt nach dem letzten Gast-Wort schon
        # der naechste (fremde) Sprecher, darf das End-Padding nicht in dessen Stimme
        # laufen. Nur bei Antwort-Bloecken (fester Gast); bei 'quelle' (beliebiger
        # Sprecher) gibt es kein "fremd".
        hard_end = None
        if is_answer and speaker:
            last_end = ws[-1]["end"]
            nxt = [w["start"] for w in words
                   if w["start"] >= last_end and w.get("speaker_id") != speaker]
            if nxt:
                hard_end = min(nxt)
        ranges = tc.build_ranges(ws, gap, hard_end=hard_end)
        tokens = tc.clean_tokens(ws, fixes, spellings)
        dur = round(sum(r[1] - r[0] for r in ranges), 2)
        # Ken-Burns-Push auf den Gast nur bei laengeren Antworten (nicht bei kurzen
        # Zitaten wie Begruessung/Abschluss, die 'quelle' statt 'antwort' nutzen).
        # zoomcfg kann leer sein (--zoom ohne Config-Block) -> Defaults nutzen,
        # aber ein truthy Dict weiterreichen, damit build_clip den Zoom anwendet.
        zoom = (zoomcfg or {"enabled": True}) if (zoom_on and is_answer and dur >= zoom_min) else None
        planned.append({**b, "kind": kind, "ranges": ranges, "tokens": tokens,
                        "dur": dur, "zoom": zoom})
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
            # Optionales Kunden-Logo (logo: <pfad> im [intro]-Block), relativ zum Projekt.
            logo_rel = b.get("logo", "").strip()
            intro_logo = ""
            if logo_rel:
                lp = (proj / logo_rel).resolve()
                if lp.exists():
                    intro_logo = f"<img class='intro-logo' src='file://{lp}'>"
                else:
                    print(f"  [warn] Kunden-Logo nicht gefunden: {lp}")
            html = tc.card_html(brand, "intro", {
                "eyebrow": b.get("eyebrow", "Kundenstimme"), "name": b.get("name", ""),
                "rolle": b.get("rolle", ""), "meta": b.get("meta", ""),
                "intro_logo": intro_logo})
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


def build(projekt: str, push: bool = True, zoom_experiment: bool = False) -> Path:
    cfg, planned = plan(projekt, zoom_experiment)
    proj = tc.project_dir(projekt)
    src = proj / cfg["quelle"]
    # Antworten laufen ueber dem Video: dort das WEISSE Logo (das dunkle verschwindet
    # im bunten Hintergrund des Gasts). Die weissen Folien behalten das farbige —
    # gleiche Stelle, gleiche Groesse, es wechselt nur die Variante.
    logo = tc.REPO_ROOT / "brand-guidelines" / cfg["brand"] / tc.LOGO_HELL
    band, bg = cfg["band"], cfg["hintergrund"]
    kd = cfg["karten"]
    # Vollbild-Modus: nur der Gast, formatfuellend (Juliana faellt weg). Ersetzt
    # den Zwei-Shot; der Zoom ist dann hinfaellig.
    vollbild = cfg["vollbild"] if cfg.get("vollbild", {}).get("enabled") else None

    render_cards(projekt, cfg, planned)

    clips: list[Path] = []
    expected = 0.0
    for b in planned:
        k, name = b["kind"], b["block"]
        slug = slugify(name)
        if b.get("card") is not None:
            dur = kd["intro_s"] if k == "intro" else kd["outro_s"] if k == "outro" else kd["frage_s"]
            # Outro NICHT nach Schwarz ausblenden — sonst wird der CTA-Text am
            # Ende unlesbar (und das letzte Bild taugt nicht als Poster/Vorschau).
            # Nur das Intro sanft aus Schwarz einblenden.
            c = tc.build_card_clip(b["card"], proj / "work" / f"card_{slug}.mp4", dur,
                                   fade_in=(k == "intro"), fade_out=False)
            clips.append(c)
            expected += dur
        if b.get("ranges"):
            srt = proj / "work" / f"{slug}.srt"
            srt.write_text(tc.build_srt(b["ranges"], b["tokens"]))
            c = tc.build_clip(src, logo, b["ranges"], srt, band, bg, SUB_STYLE,
                              proj / "work" / f"{slug}.mp4",
                              zoom=None if vollbild else b.get("zoom"), vollbild=vollbild)
            clips.append(c)
            expected += b["dur"]
            cuts = len(b["ranges"]) - 1
            zmark = "  +Zoom" if b.get("zoom") else ""
            print(f"  [build] {name:14s} {b['dur']:6.1f}s  {cuts} Schnitt(e){zmark}")

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

    # Sprecher-ID-Box (Kundenlogo + Name + Rolle unten rechts, nur waehrend der
    # Antworten). Sie war frueher ein Handgriff NACH dem Build — dabei ist sie bei
    # jedem Rebuild still verloren gegangen. Deshalb laeuft sie hier mit, sobald die
    # testimonial.json einen `idbox`-Block mit "enabled": true hat.
    fertig = out
    ib = cfg.get("idbox") or {}
    if ib.get("enabled"):
        intro = tt.intro_felder(projekt)
        thumb = cfg.get("thumbnail") or {}
        mit_box = out.with_name(f"{out.stem}_idbox.mp4")
        fertig = ti.apply(
            projekt, out, mit_box,
            ib.get("name") or intro.get("name", ""),
            ib.get("rolle") or thumb.get("rolle") or intro.get("rolle", ""),
            # NICHT auf thumbnail.kunde_logo zurueckfallen: die Box ist eine WEISSE
            # Karte, das Thumbnail eine dunkle — dort liegt oft die weisse Fassung
            # des Kundenlogos, und die waere hier unsichtbar.
            proj / (ib.get("logo") or "assets/kunde-logo.png"))

    # Thumbnail gehoert zum Liefergegenstand: der Nutzer bettet das Video selbst
    # auf der Website ein und sieht dort vor dem Klick NUR dieses Bild.
    # Laeuft nach dem Video-Push, damit der Freigabe-Ordner schon existiert.
    if push:
        push_freigabe(projekt, cfg, fertig, version)
    try:
        # Standbild aus der Fassung OHNE Box — sie sitzt unten rechts und haette
        # sonst eine Chance, in den Portraet-Ausschnitt zu rutschen.
        bild = tt.build(projekt, video=out, version=version)
        if bild and push:
            tt.push(projekt, cfg, bild, freigabe_folder(cfg), slugify(projekt))
    except Exception as e:  # ein kaputtes Logo darf den Video-Build nie kippen
        print(f"  [thumb] uebersprungen: {e}")
    return fertig


def freigabe_folder(cfg: dict) -> Path:
    # Testimonials haben einen eigenen Freigabe-Ordner (getrennt von den Social-Video-
    # Posts). Reihenfolge: projektspezifischer Override in testimonial.json
    # ("freigabe_dir") > Umgebungsvariable FREIGABE_TESTIMONIAL_DIR > Default.
    base = (cfg.get("freigabe_dir")
            or os.environ.get("FREIGABE_TESTIMONIAL_DIR")
            or DEFAULT_TESTIMONIAL_FREIGABE_DIR)
    return Path(base)


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
    ap.add_argument("--zoom", action="store_true",
                    help="Zoom-Experiment fuer DIESEN Build aktivieren (Standard: aus). Der Ken-Burns-"
                         "Push auf den Gast ist bewusst kein Automatismus — pro Video ausprobieren "
                         "und Feedback abwarten.")
    args = ap.parse_args()

    if args.nur_plan:
        _, planned = plan(args.projekt, zoom_experiment=args.zoom)
        for b in planned:
            if b.get("ranges"):
                print(f"\n### {b['block']}  {b['dur']}s  {len(b['ranges']) - 1} Schnitt(e)  {b['ranges']}")
                print("   ", " ".join(t["t"] for t in b["tokens"]))
        return
    build(args.projekt, push=not args.no_push, zoom_experiment=args.zoom)


if __name__ == "__main__":
    main()
