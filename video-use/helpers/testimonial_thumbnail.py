#!/usr/bin/env python3
"""Testimonial-Thumbnail — Poster-Bild fuer den Website-Embed.

Der Nutzer laedt fertige Testimonials selbst auf die Palstek-Website. Vor dem
Klick sieht ein Besucher NUR dieses Bild, deshalb muss es allein tragen, wer
spricht, fuer welches Unternehmen und worum es ging. Pflichtinhalte:

    Palstek-Logo · Kundenlogo · Name + Rolle · Inhalt der Zusammenarbeit

Format: 1920x1080 (16:9) PNG — bewusst gross, nicht Daumennagel-Groesse.

Laeuft automatisch als letzter Schritt von `testimonial_build.py` (und damit von
`npm run testimonial:build`), sobald `testimonial.json` einen `thumbnail`-Block
hat. Einzeln:

    npm run testimonial:thumbnail -- --projekt <name>

Konfiguration in `projects/<projekt>/testimonial.json`:

    "thumbnail": {
      "kunde_logo": "assets/kunde-logo.png",   // Datei ODER https-URL
      "zitat": "Wir haben alle einen stressigen Job. ...",
      "zitat_highlight": "teilweise sind sogar die Krankheitszeiten zurueckgegangen",
      "produkt": "Workshops fuer Mitarbeitende",
      "produkt_sub": "Selbstfuehrung im Arbeitsalltag, inklusive Workbook",
      "portrait_s": 135.2,                     // Sekunde im FERTIGEN Video
      "portrait_crop": [722, 58, 1292, 628],   // optional, sonst automatisch
      "rolle": "WP, StB & Partner"             // optional: kurze Rolle fuers Thumbnail
    }

Name, Rolle und Eyebrow kommen aus dem `[intro]`-Block der `interview.txt` —
sie stehen dort schon fuer die Intro-Folie und werden nicht doppelt gepflegt.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import testimonial_common as tc  # noqa: E402

HELPERS = Path(__file__).resolve().parent
REPO = tc.REPO_ROOT
TPL = HELPERS / "composition_templates" / "testimonial-thumbnail.html"
RENDERER = HELPERS / "render_image_post.cjs"
FONT = REPO / "font_kobin_medium" / "Korbin-Medium.otf"

W, H = 1920, 1080
LABEL = "Inhalt der Zusammenarbeit"   # NICHT "Gebucht" — Kundenwunsch.
EYEBROW = "Kundenstimme"


def _url(p: Path) -> str:
    return "file://" + str(p)


# ----------------------------------------------------------- Kundenlogo ------

def _fetch(src: str, dest: Path, base: Path) -> Path:
    """Kundenlogo besorgen — lokale Datei (relativ zum Projekt) oder URL."""
    if src.startswith(("http://", "https://")):
        with urllib.request.urlopen(src, timeout=30) as r, dest.open("wb") as f:
            shutil.copyfileobj(r, f)
        return dest
    p = Path(src)
    if not p.is_absolute():
        p = base / src
    if not p.exists():
        raise FileNotFoundError(f"Kundenlogo nicht gefunden: {p}")
    shutil.copy2(p, dest)
    return dest


def freistellen(src: Path, out_hell: Path, out_dunkel: Path) -> None:
    """Weissen Hintergrund entfernen und zwei Varianten schreiben.

    Zwei Fallstricke, beide teuer gelernt:

    1) NICHT einfach alles Weisse transparent setzen — Logos haben oft weisse
       Glanzlichter INNERHALB der Grafik (z.B. auf einer Kugel). Deshalb Flood-Fill
       vom Bildrand: nur aussen liegendes Weiss faellt weg.
    2) NICHT nur reines Weiss entfernen — die weichen Kanten des Originals
       bleiben sonst als grauer Saum stehen. Stattdessen die Deckung aus der
       Helligkeit ableiten und die Schrift direkt in der Zielfarbe einfaerben.
       Der farbige Teil des Logos (Bildmarke) bleibt unangetastet.
    """
    from PIL import Image
    import numpy as np

    im = Image.open(src)
    if im.mode in ("RGBA", "LA") or "transparency" in im.info:
        # Sonderfall: das Logo ist SCHON freigestellt und hell (weisse Fassung vom
        # Kunden). Dann waere jede Weiss-Erkennung toedlich — sie wuerde das Logo
        # selbst wegradieren. Direkt uebernehmen, nur die dunkle Fassung einfaerben.
        rgba = im.convert("RGBA")
        arr = np.array(rgba)
        deckend = arr[arr[..., 3] > 128][:, :3]
        if len(deckend) and float(deckend.mean()) > 200:
            # Zuschnitt auf SICHTBARE Deckung: getbbox() allein zaehlt auch Alpha 1
            # mit, und solche Reste liegen in Export-PNGs oft im ganzen Rand — das
            # Logo landet dann winzig in einer riesigen leeren Box.
            bbox = rgba.getchannel("A").point(lambda v: 255 if v > 25 else 0).getbbox()
            rgba.crop(bbox).save(out_dunkel)
            dunkel = np.array(rgba.crop(bbox)).copy()
            dunkel[..., :3] = (40, 29, 103)
            Image.fromarray(dunkel).save(out_hell)
            return
        # Sonst: Transparenz ist da, das Logo aber dunkel (Website-Downloads oft).
        # NICHT einfach convert("RGB") — dabei wird der transparente Rand SCHWARZ
        # und gilt unten als volle Deckung; das Logo bekommt einen Kasten. Erst auf
        # Weiss legen, dann greift die Flood-Fill-Logik wie bei einem weissen Original.
        weiss = Image.new("RGB", rgba.size, (255, 255, 255))
        weiss.paste(rgba, mask=rgba.getchannel("A"))
        im = weiss
    else:
        im = im.convert("RGB")
    a = np.array(im).astype(np.float32)
    h, w, _ = a.shape
    lum = a.min(2)
    sat = a.max(2) - a.min(2)

    white = (lum >= 246) & (sat < 12)
    seen = np.zeros((h, w), bool)
    q: deque = deque()
    for x in range(w):
        for y in (0, h - 1):
            if white[y, x] and not seen[y, x]:
                seen[y, x] = True
                q.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if white[y, x] and not seen[y, x]:
                seen[y, x] = True
                q.append((y, x))
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and white[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                q.append((ny, nx))

    mark = np.zeros((h, w), bool)
    ys, xs = np.where(sat > 45)
    if len(ys):                      # farbige Bildmarke vorhanden
        mark[max(ys.min() - 3, 0):ys.max() + 3, max(xs.min() - 3, 0):xs.max() + 3] = True
        mark &= ~seen

    text_area = (~mark) & (~seen)
    solid = np.percentile(lum[text_area], 1.0) if text_area.any() else 0.0
    cov = np.clip((255.0 - lum) / max(255.0 - solid, 1.0), 0, 1)
    cov[seen] = 0.0
    cov[mark] = 1.0

    def write(rgb: tuple[int, int, int], dest: Path) -> None:
        out = np.zeros((h, w, 4), np.uint8)
        out[..., :3] = np.where(mark[..., None], a.astype(np.uint8), np.array(rgb, np.uint8))
        out[..., 3] = (cov * 255).astype(np.uint8)
        img = Image.fromarray(out)
        img.crop(img.getchannel("A").getbbox()).save(dest)

    write((90, 90, 90), out_hell)
    write((255, 255, 255), out_dunkel)


# -------------------------------------------------------------- Portrait -----

def portrait(video: Path, sekunde: float, crop: list[int] | None, dest: Path) -> None:
    """Standbild aus dem fertigen Video ziehen und rund beschneiden.

    Der Kreis braucht LUFT um den Kopf — eng am Scheitel wirkt beklemmt
    (Kundenfeedback). Richtwert: Augen bei ~44 % der Ausschnitthoehe.
    """
    from PIL import Image, ImageFilter

    raw = dest.with_name("_frame.png")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(sekunde), "-i", str(video),
                    "-frames:v", "1", str(raw)], check=True)
    im = Image.open(raw).convert("RGB")
    # Untertitel-Streifen des Testimonials unten abschneiden, sonst landet er im Kreis.
    im = im.crop((0, 0, im.width, int(im.height * 0.75)))
    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=3))
    if crop and len(crop) == 4:
        im = im.crop(tuple(crop))
    else:
        side = int(im.height * 0.72)
        cx, cy = im.width // 2, int(im.height * 0.46)
        im = im.crop((cx - side // 2, max(cy - side // 2, 0),
                      cx + side // 2, max(cy - side // 2, 0) + side))
    im.resize((820, 820), Image.LANCZOS).save(dest)
    raw.unlink(missing_ok=True)


# --------------------------------------------------------------- Aufbau ------

def intro_felder(projekt: str) -> dict:
    for b in tc.parse_interview(tc.project_dir(projekt) / "interview.txt"):
        if b["block"].split()[0].lower() == "intro":
            return b
    return {}


def build(projekt: str, video: Path | None = None, version: int | None = None) -> Path | None:
    cfg = tc.load_config(projekt)
    t = cfg.get("thumbnail")
    if not t:
        print("  [thumb] kein 'thumbnail'-Block in testimonial.json — uebersprungen.\n"
              "          Pflichtfelder: kunde_logo, zitat, produkt, produkt_sub, portrait_s")
        return None

    proj = tc.project_dir(projekt)
    work = proj / "thumbnails"
    (work / "assets").mkdir(parents=True, exist_ok=True)

    if video is None:
        renders = sorted((proj / "renders").glob("testimonial_v*.mp4"),
                         key=lambda p: int(re.search(r"_v(\d+)", p.name).group(1)))
        if not renders:
            print("  [thumb] kein gerendertes Video gefunden — erst testimonial:build laufen lassen.")
            return None
        video = renders[-1]

    hell = work / "assets" / "kunde-logo.png"
    dunkel = work / "assets" / "kunde-logo-weiss.png"
    try:
        freistellen(_fetch(t["kunde_logo"], work / "assets" / "_kunde-roh", proj), hell, dunkel)
    except Exception as e:
        print(f"  [thumb] Kundenlogo nicht verarbeitbar ({e}) — Thumbnail uebersprungen.")
        return None

    foto = work / "assets" / "portrait-rund.png"
    portrait(video, float(t.get("portrait_s", 5.0)), t.get("portrait_crop"), foto)

    intro = intro_felder(projekt)
    felder = {
        "font": _url(FONT),
        "logo_palstek": _url(REPO / "brand-guidelines" / cfg["brand"] / "assets/logo-horizontal.png"),
        "logo_kunde": _url(dunkel),
        "portrait": _url(foto),
        "eyebrow": t.get("eyebrow", EYEBROW),
        "zitat": tc.emphasise(t["zitat"], t.get("zitat_highlight")),
        "name": intro.get("name", projekt),
        # Die Intro-Folie hat Platz fuer die volle Rolle, das Thumbnail nicht — dort
        # steht rechts daneben der Produktblock. Zu lange Rollen laufen ineinander,
        # deshalb hier eine kurze Fassung erlauben (Default: die aus dem Intro).
        "rolle": t.get("rolle") or intro.get("rolle", ""),
        "label": t.get("label", LABEL),
        "produkt": t.get("produkt", ""),
        "produkt_sub": t.get("produkt_sub", ""),
    }
    # Bewusst str.replace statt str.format: das Template enthaelt CSS-Klammern.
    html = TPL.read_text(encoding="utf-8")
    for k, v in felder.items():
        html = html.replace("{" + k + "}", str(v))
    page = work / "thumbnail.html"
    page.write_text(html, encoding="utf-8")

    if version is None:
        vs = [int(m.group(1)) for p in work.glob("thumbnail_v*.png")
              if (m := re.match(r"thumbnail_v(\d+)\.png$", p.name))]
        version = (max(vs) + 1) if vs else 1
    out = work / f"thumbnail_v{version}.png"
    subprocess.run(["node", str(RENDERER), str(page), str(out), str(W), str(H)],
                   check=True, cwd=str(REPO))
    print(f"  [thumb] {out}")
    return out


def push(projekt: str, cfg: dict, bild: Path, freigabe_dir: Path, titel: str) -> None:
    """Neben das Video legen — der Nutzer schaut ausschliesslich im Freigabe-Ordner."""
    folder = cfg.get("freigabe_folder")
    if not folder:
        return
    dest_dir = freigabe_dir / folder
    if not dest_dir.exists():
        return
    vs = [int(m.group(1)) for p in dest_dir.glob("thumbnail_v*.png")
          if (m := re.match(r"thumbnail_v(\d+)__", p.name))]
    dest = dest_dir / f"thumbnail_v{(max(vs) + 1) if vs else 1}__{titel}.png"
    shutil.copy2(bild, dest)
    print(f"  [push] {dest}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Testimonial-Thumbnail (1920x1080) bauen")
    ap.add_argument("--projekt", required=True)
    ap.add_argument("--video", type=Path, help="Quelle fuer das Standbild (Default: neuester Render)")
    args = ap.parse_args()
    out = build(args.projekt, args.video)
    if out is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
