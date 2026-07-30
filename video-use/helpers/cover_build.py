#!/usr/bin/env python3
"""
Reel-Cover-Generator — erzeugt ein eigenständiges Titelbild (1080x1920 / 9:16)
für ein Video-Post/Reel. KEIN Video wird verändert; das Cover ist eine separate PNG,
die im Profil als Reel-Vorschaubild/Cover hinterlegt wird (sorgt für ein einheitliches,
ordentliches Grid in LinkedIn/Instagram).

Design (fix, an den Reel-Hook angelehnt):
  - sauberer Standbild-Frame aus dem Reel (base.mp4 = Cut ohne eingebrannte Untertitel)
  - flaches Corporate-Dunkelblau-Overlay #281D67 @ 50% (KEIN Verlauf)
  - Titel: Montserrat fett, Punchline in Teal-Marker-Box #4ebbc2, Akzent in Teal
  - KEIN Logo, KEINE Eyebrow (bewusst — wie andere Reels in Julianas Profil)
  - Titelblock in der Grid-Sicherheitszone (auch beschnitten vollständig sichtbar)

Frame-Wahl: standardmäßig automatisch bei ~40% der Videolänge (ruhiger Mittelteil).
Die Prüfung/ggf. Neuwahl passiert im Rahmen der Freigabe. Überschreibbar via --t / --foto.

Titel-Mini-Syntax (--zeilen, Zeilen mit "|" trennen):
  *Wort*   -> große Teal-Marker-Box (die Punchline-Zeile)
  ~Wort~   -> Teal-Akzentfarbe
  sonst    -> weiß
Zeilen VOR der Marker-Zeile werden groß (.top, 104px), die Marker-Zeile 172px,
Zeilen DANACH etwas kleiner (.bot, 78px, zu einem Block zusammengefasst).

Beispiel:
  python cover_build.py --projekt 2026-06-28_Buesum__02 \
    --zeilen "Schau in den | *Spiegel* | wenn dein Team | ~nicht funktioniert.~"
"""
import argparse
import html
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).resolve().parent / "composition_templates" / "reel-cover.html"
RENDER_CJS = Path(__file__).resolve().parent / "render_image_post.cjs"


def ffprobe_duration(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def extract_frame(video: Path, t: float, out_jpg: Path) -> None:
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(video),
         "-frames:v", "1", "-q:v", "2", str(out_jpg), "-loglevel", "error"],
        check=True,
    )


def _spans(text: str) -> str:
    """~x~ -> Teal-Span; Text wird escaped, Marker bleiben."""
    parts = re.split(r"(~[^~]+~)", text)
    out = []
    for p in parts:
        if p.startswith("~") and p.endswith("~") and len(p) >= 2:
            out.append(f'<span class="tl">{html.escape(p[1:-1])}</span>')
        else:
            out.append(html.escape(p))
    return "".join(out)


def mark_font_px(zeilen: str) -> int:
    """Marker-Box-Schriftgröße so wählen, dass das Wort in den Titelrahmen passt
    (Rahmen ~904px breit; Box-Padding ~52px). Kurze Wörter behalten 172px."""
    for line in zeilen.split("|"):
        m = re.search(r"\*([^*]+)\*", line)
        if m:
            n = max(1, len(m.group(1)))
            return max(110, min(215, int((950 - 52) / (n * 0.60))))
    return 215


def build_title_html(zeilen: str) -> str:
    lines = [z.strip() for z in zeilen.split("|") if z.strip()]
    mark_idx = next((i for i, l in enumerate(lines) if "*" in l), None)
    parts = []
    bot_lines = []
    for i, line in enumerate(lines):
        if mark_idx is not None and i == mark_idx:
            inner = re.sub(r"\*([^*]+)\*",
                           lambda m: f'<span class="mark">{html.escape(m.group(1))}</span>',
                           line)
            parts.append(f'<div class="mark-line">{inner}</div>')
        elif mark_idx is not None and i > mark_idx:
            bot_lines.append(_spans(line))
        else:
            parts.append(f'<div class="top">{_spans(line)}</div>')
    if bot_lines:
        parts.append(f'<div class="bot">{"<br>".join(bot_lines)}</div>')
    return "\n      ".join(parts)


def next_version(renders: Path) -> int:
    existing = [int(m.group(1)) for p in renders.glob("cover_v*.png")
                if (m := re.match(r"cover_v(\d+)\.png$", p.name))]
    return (max(existing) + 1) if existing else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Reel-Cover (Titelbild) erzeugen")
    ap.add_argument("--projekt", required=True, help="Projektordner unter projects/")
    ap.add_argument("--zeilen", required=True,
                    help='Titel-Mini-Syntax, Zeilen mit "|" getrennt (*Box*, ~Teal~)')
    ap.add_argument("--video", type=Path, default=None,
                    help="Quellvideo für den Frame (Default: <projekt>/base.mp4)")
    ap.add_argument("--t", type=float, default=None,
                    help="Frame-Zeitpunkt in Sekunden (Default: ~40%% der Länge)")
    ap.add_argument("--foto", type=Path, default=None,
                    help="Statt Video-Frame ein fertiges Foto verwenden")
    ap.add_argument("--objectpos", default="50% 16%",
                    help='CSS object-position des Fotos (Default "50%% 16%%")')
    ap.add_argument("--out", type=Path, default=None,
                    help="Ausgabepfad (Default: <projekt>/renders/cover_vN.png)")
    args = ap.parse_args()

    proj = REPO / "projects" / args.projekt
    if not proj.is_dir():
        sys.exit(f"Projektordner nicht gefunden: {proj}")
    renders = proj / "renders"
    renders.mkdir(exist_ok=True)
    work = renders / "_cover"
    work.mkdir(exist_ok=True)

    # 1) Foto besorgen (Video-Frame oder gepinntes Foto)
    frame = work / "frame.jpg"
    if args.foto:
        src = args.foto if args.foto.is_absolute() else (REPO / args.foto)
        if not src.exists():
            sys.exit(f"Foto nicht gefunden: {src}")
        frame.write_bytes(src.read_bytes())
        print(f"Foto: {src}")
    else:
        video = args.video or (proj / "base.mp4")
        video = video if video.is_absolute() else (REPO / video)
        if not video.exists():
            sys.exit(f"Quellvideo nicht gefunden: {video}")
        dur = ffprobe_duration(video)
        t = args.t if args.t is not None else round(0.40 * dur, 2)
        print(f"Frame aus {video.name} bei t={t:.2f}s (Dauer {dur:.1f}s)")
        extract_frame(video, t, frame)

    # 2) Titel + Template füllen
    title_html = build_title_html(args.zeilen)
    tpl = TEMPLATE.read_text()
    filled = (tpl
              .replace("{{PHOTO_SRC}}", "frame.jpg")
              .replace("{{OBJECT_POS}}", args.objectpos)
              .replace("{{MARK_FONT}}", str(mark_font_px(args.zeilen)))
              .replace("{{TITLE_HTML}}", title_html))
    cover_html = work / "cover.html"
    cover_html.write_text(filled)

    # 3) Rendern
    out = args.out or (renders / f"cover_v{next_version(renders)}.png")
    out = out if out.is_absolute() else (REPO / out)
    subprocess.run(
        ["node", str(RENDER_CJS), str(cover_html), str(out), "1080", "1920"],
        check=True,
    )
    print(f"\nCover fertig: {out}")


if __name__ == "__main__":
    main()
