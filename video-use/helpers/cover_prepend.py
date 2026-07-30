#!/usr/bin/env python3
"""
Cover-Vorspann — schneidet ein Cover-Standbild (PNG) als kurzen Intro-Frame VOR
ein fertiges Reel. Das separate Cover-Bild (fürs Profil-Grid) bleibt davon unberührt;
hier entsteht zusätzlich eine Video-Fassung, die MIT dem Cover beginnt.

Der Vorspann wird exakt an die Parameter des Zielvideos angepasst (Auflösung, fps,
SAR, Audio-Samplerate/Kanäle), damit die Concat sauber ist. Während des Cover-Halts
läuft Stille (Titelkarte); danach spielt das Reel unverändert weiter.

Usage:
  python cover_prepend.py --cover <cover.png> --video <final.mp4> [--hold 1.5] [--out <mp4>]
"""
import argparse
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def probe(video: Path) -> dict:
    def kv(stream, entries):
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", stream,
             "-show_entries", entries, "-of", "default=noprint_wrappers=1", str(video)],
            capture_output=True, text=True, check=True,
        ).stdout
        d = {}
        for line in out.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                d[k.strip()] = v.strip()
        return d
    v = kv("v:0", "stream=width,height,r_frame_rate,sample_aspect_ratio")
    a = kv("a:0", "stream=sample_rate,channels")
    rfr = v.get("r_frame_rate", "30/1")
    sar = v.get("sample_aspect_ratio", "1:1")
    fps = float(Fraction(rfr)) if "/" in rfr else float(rfr or 30)
    return {"w": int(v.get("width", 1080)), "h": int(v.get("height", 1920)),
            "fps": round(fps, 4),
            "sar": sar if sar and sar not in ("N/A", "") else "1",
            "sr": a.get("sample_rate", "48000"), "ch": int(a.get("channels", 2))}


def next_final(renders: Path) -> Path:
    import re
    nums = [int(m.group(1)) for p in renders.glob("final_v*.mp4")
            if (m := re.match(r"final_v(\d+)\.mp4$", p.name))]
    n = (max(nums) + 1) if nums else 2  # final.mp4 zählt als v1
    return renders / f"final_v{n}.mp4"


def main() -> None:
    ap = argparse.ArgumentParser(description="Cover als Vorspann vor ein Reel schneiden")
    ap.add_argument("--cover", type=Path, required=True, help="Cover-PNG (1080x1920)")
    ap.add_argument("--video", type=Path, required=True, help="Ziel-Reel (final.mp4)")
    ap.add_argument("--hold", type=float, default=0.5,
                    help="Cover-Haltezeit in Sekunden (Default 0.5 — nur kurzer Blickfang, dann sofort Inhalt)")
    ap.add_argument("--out", type=Path, default=None, help="Ausgabepfad (Default: nächstes final_vN.mp4)")
    args = ap.parse_args()

    cover = args.cover if args.cover.is_absolute() else REPO / args.cover
    video = args.video if args.video.is_absolute() else REPO / args.video
    for f in (cover, video):
        if not f.exists():
            sys.exit(f"Datei nicht gefunden: {f}")

    p = probe(video)
    cl = "stereo" if p["ch"] == 2 else ("mono" if p["ch"] == 1 else f"{p['ch']}c")
    out = args.out or next_final(video.parent)
    out = out if out.is_absolute() else REPO / out

    vf = (f"[0:v]scale={p['w']}:{p['h']},setsar={p['sar']},"
          f"fps={p['fps']},format=yuv420p[cv];"
          f"[cv][1:a][2:v][2:a]concat=n=2:v=1:a=1[v][a]")
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", f"{args.hold}", "-i", str(cover),
        "-f", "lavfi", "-t", f"{args.hold}", "-i", f"anullsrc=r={p['sr']}:cl={cl}",
        "-i", str(video),
        "-filter_complex", vf,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", p["sr"],
        "-movflags", "+faststart",
        str(out),
    ]
    print(f"Ziel-Parameter: {p['w']}x{p['h']} @ {p['fps']}fps, Audio {p['sr']}Hz/{cl}")
    print(f"Cover-Halt: {args.hold}s  →  {out}")
    subprocess.run(cmd, check=True)
    print(f"\nFertig: {out}")


if __name__ == "__main__":
    main()
