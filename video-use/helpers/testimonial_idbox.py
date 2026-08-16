"""Sprecher-ID-Box fuer Testimonial-Videos (Post-Overlay).

Blendet unten rechts eine kleine weisse Karte ein: Kunden-Logo + Name + Rolle.
Sichtbar NUR waehrend der Talking-Head-Antworten (Nicht-`card_`-Segmente); auf
Intro-/Fragen-/Fazit-/Outro-Folien ist sie aus (dort steht der Name auf der Folie).

Die Sichtbarkeits-Fenster kommen aus `renders/concat.txt`: jedes gelistete Clip
ist entweder eine Folie (Dateiname beginnt mit `card_`) oder eine Antwort. Aus den
gemessenen Dauern werden die Antwort-Zeitfenster im fertigen Video kumuliert; ein
kleiner Inset je Seite schuetzt vor Bleed auf die angrenzenden Folien-Frames.

Usage:
    uv run --project ./video-use python ./video-use/helpers/testimonial_idbox.py \
        --projekt testimonial-christoph \
        --input renders/testimonial_v5.mp4 \
        --out   renders/testimonial_v5_idbox.mp4 \
        --name  "Christoph Donnevert" \
        --rolle "WP, StB & Partner" \
        --logo  assets/kunde-logo.png
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import testimonial_common as tc  # noqa: E402

RENDERER = tc.HELPERS / "render_transparent.cjs"
FONT = tc.REPO_ROOT / "font_kobin_medium" / "Korbin-Medium.otf"

# Randabstand je Antwort-Fenster: die Box erst knapp nach dem Folien-Schnitt zeigen
# und knapp vorher ausblenden, damit sie nie auf einem Folien-Frame aufblitzt.
INSET_S = 0.12

BOX_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  @font-face {{ font-family:'Korbin'; src:url('file://{font}') format('opentype'); font-weight:500; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ width:1920px; height:1080px; background:transparent; }}
  body {{ font-family:'Korbin', system-ui, sans-serif; -webkit-font-smoothing:antialiased; }}
  .idbox {{
    position:absolute; right:24px; bottom:20px; width:440px;
    background:#ffffff; border:1.5px solid #e7e7f0; border-radius:26px;
    box-shadow:0 10px 30px rgba(40,29,103,0.16); padding:26px 30px 24px; text-align:center;
  }}
  .idbox .logo {{ width:320px; max-width:100%; height:auto; display:block; margin:0 auto 18px; }}
  .idbox .name {{ font-size:34px; font-weight:700; color:#281d67; line-height:1.04;
                 letter-spacing:-0.5px; white-space:nowrap; }}
  .idbox .role {{ font-size:26px; font-weight:500; color:#475569; margin-top:7px; }}
</style></head>
<body>
  <div class="idbox">
    <img class="logo" src="file://{logo}">
    <div class="name">{name}</div>
    <div class="role">{role}</div>
  </div>
</body></html>
"""


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def answer_windows(concat_txt: Path) -> list[tuple[float, float]]:
    """Zeitfenster (im fertigen Video) aller Nicht-`card_`-Clips, kumuliert."""
    wins: list[tuple[float, float]] = []
    cum = 0.0
    for line in concat_txt.read_text().splitlines():
        line = line.strip()
        if not line.startswith("file "):
            continue
        p = Path(line[5:].strip().strip("'\""))
        dur = float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(p)]).strip())
        start, cum = cum, cum + dur
        if not p.name.startswith("card_"):
            wins.append((start + INSET_S, cum - INSET_S))
    return wins


def render_box(png: Path, logo: Path, name: str, role: str) -> None:
    html = BOX_HTML.format(font=FONT, logo=logo.resolve(),
                           name=_esc(name), role=_esc(role))
    tmp = png.with_suffix(".html")
    tmp.write_text(html)
    subprocess.run(["node", str(RENDERER), str(tmp), str(png), "1920", "1080"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def apply(projekt: str, inp: Path, out: Path, name: str, rolle: str,
          logo: Path) -> Path:
    """Box ins fertige Video brennen. Wird von testimonial_build mitgerufen."""
    proj = tc.project_dir(projekt)
    for p in (inp, logo, proj / "renders" / "concat.txt"):
        if not p.exists():
            sys.exit(f"  [fehler] nicht gefunden: {p}")

    wins = answer_windows(proj / "renders" / "concat.txt")
    if not wins:
        sys.exit("  [fehler] keine Antwort-Segmente in concat.txt gefunden")
    enable = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in wins)
    print(f"  [idbox] {len(wins)} Antwort-Fenster, Box sichtbar von "
          f"{wins[0][0]:.1f}s bis {wins[-1][1]:.1f}s")

    box_png = proj / "work" / "idbox.png"
    render_box(box_png, logo, name, rolle)
    print(f"  [idbox] Box gerendert: {box_png}")

    graph = f"[0:v][1:v]overlay=0:0:enable='{enable}'[vo]"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(inp), "-i", str(box_png),
         "-filter_complex", graph, "-map", "[vo]", "-map", "0:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "copy", "-movflags", "+faststart", str(out)],
        check=True)

    info = tc.probe(out)
    print(f"  [ok] {out}  ({info['duration']:.1f}s, {info['codecs']})")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Testimonial: Sprecher-ID-Box overlay")
    ap.add_argument("--projekt", required=True)
    ap.add_argument("--input", required=True, help="Eingangsvideo (relativ zum Projekt)")
    ap.add_argument("--out", required=True, help="Ausgangsvideo (relativ zum Projekt)")
    ap.add_argument("--name", required=True)
    ap.add_argument("--rolle", required=True)
    ap.add_argument("--logo", default="assets/kunde-logo.png")
    args = ap.parse_args()

    proj = tc.project_dir(args.projekt)
    apply(args.projekt, proj / args.input, proj / args.out,
          args.name, args.rolle, proj / args.logo)


if __name__ == "__main__":
    main()
