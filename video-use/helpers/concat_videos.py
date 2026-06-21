#!/usr/bin/env python3
"""
Concatenate several clips (named 1, 2, 3, …) into ONE video in order, then hand
it to the normal batch pipeline — the opposite of podcast_split.

Use it when you filmed a reel in parts (intro / point / outro) and want them
stitched, then cut + B-roll + zoom + caption + Metricool-draft like everything else.

Clips are ordered by the leading number in the filename (1.mp4, 2.mov, 03-outro.mp4 …).
They're normalised to the FIRST clip's resolution (scale-to-fit + pad, 30fps,
h264/aac) so clips from different phones/formats join cleanly.

Usage:
    python concat_videos.py --input-dir raw/concat/mein-reel --brand default
    python concat_videos.py --inputs a.mp4 b.mp4 c.mp4 --brand default --name mein-reel
    python concat_videos.py --input-dir raw/concat/mein-reel --brand default --auto   # also run the pipeline
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HELPERS = Path(__file__).resolve().parent
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "reel"


def _lead_num(p: Path) -> tuple[int, str]:
    """Sort key: leading integer in the filename, then name. '1'<'2'<'10'."""
    m = re.match(r"\s*0*(\d+)", p.stem)
    return (int(m.group(1)) if m else 10**9, p.stem.lower())


def resolve_inputs(args) -> list[Path]:
    if args.inputs:
        paths = [Path(p) for p in args.inputs]
    else:
        d = Path(args.input_dir)
        if not d.is_absolute():
            d = REPO_ROOT / d
        paths = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
        paths.sort(key=_lead_num)
    out = []
    for p in paths:
        p = p if p.is_absolute() else (REPO_ROOT / p)
        if not p.exists():
            print(f"ERROR: no such file: {p}", file=sys.stderr); sys.exit(2)
        out.append(p)
    return out


def probe_wh(path: Path) -> tuple[int, int]:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True)
    w, h = r.stdout.strip().split("x")[:2]
    return int(w), int(h)


def concat(inputs: list[Path], out_path: Path) -> bool:
    w, h = probe_wh(inputs[0])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y"]
    for p in inputs:
        cmd += ["-i", str(p)]
    # Normalise every input to w x h (fit + pad), 30fps, square pixels, 48k audio,
    # then concat. Handles mixed resolutions/formats without distortion.
    parts, labels = [], ""
    for i in range(len(inputs)):
        parts.append(
            f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}];"
            f"[{i}:a]aresample=48000[a{i}]"
        )
        labels += f"[v{i}][a{i}]"
    filt = ";".join(parts) + f";{labels}concat=n={len(inputs)}:v=1:a=1[outv][outa]"
    cmd += ["-filter_complex", filt, "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-800:], file=sys.stderr)
    return r.returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Stitch numbered clips into one video for the pipeline.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--input-dir", help="Folder of numbered clips (1.mp4, 2.mp4, …)")
    g.add_argument("--inputs", nargs="+", help="Explicit clips IN ORDER")
    ap.add_argument("--brand", default="default", help="Brand to produce under (default: default)")
    ap.add_argument("--batch", default=None, help="Batch name (default: concat-<name>)")
    ap.add_argument("--name", default=None, help="Output slug (default: input-dir name)")
    ap.add_argument("--engine", default="whisper", choices=["whisper", "scribe"])
    ap.add_argument("--auto", action="store_true", help="After stitching, run batch_init + pipeline")
    args = ap.parse_args()

    inputs = resolve_inputs(args)
    if len(inputs) < 2:
        print(f"ERROR: need ≥2 clips to stitch, got {len(inputs)}.", file=sys.stderr); sys.exit(2)

    name = _slugify(args.name or (Path(args.input_dir).name if args.input_dir else "reel"))
    batch = args.batch or f"concat-{name}"
    out = REPO_ROOT / "raw" / "batches" / batch / f"01-{name}.mp4"

    print(f"Stitching {len(inputs)} clip(s) → {out.relative_to(REPO_ROOT)}  (brand: {args.brand})")
    for i, p in enumerate(inputs, 1):
        print(f"  {i}. {p.name}")
    if not concat(inputs, out):
        print("ERROR: concat failed.", file=sys.stderr); sys.exit(1)

    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    print(f"✓ stitched → {out.relative_to(REPO_ROOT)} ({float(dur):.0f}s)")

    if args.auto:
        print("\n  ▶ batch_init + pipeline …")
        subprocess.run([sys.executable, str(HELPERS / "batch_init.py"), "--batch", batch,
                        "--brand", args.brand, "--engine", args.engine], cwd=str(REPO_ROOT))
        subprocess.run([sys.executable, str(HELPERS / "run_pipeline.py"), "--batch", batch],
                       cwd=str(REPO_ROOT))
    else:
        print(f"\nNext:  npm run batch:init -- --batch {batch} --brand {args.brand}")
        print(f"       npm run batch:pipeline -- --batch {batch}")
        print(f"       npm run metricool:push:draft -- --batch {batch}")


if __name__ == "__main__":
    main()
