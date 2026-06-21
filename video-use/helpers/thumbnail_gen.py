"""Extract a single-frame thumbnail from a video.

Used by Phase 4 (after render) to populate the review dashboard.

Usage:
    python helpers/thumbnail_gen.py <video> <out_jpg>
    python helpers/thumbnail_gen.py <video> <out_jpg> --t 2.5 --width 720
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def make_thumbnail(
    video: Path,
    out_jpg: Path,
    t: float = 1.5,
    width: int | None = None,
    quality: int = 2,
) -> Path:
    """Extract a single frame from `video` at time `t` (seconds).

    Args:
        video: source video file
        out_jpg: destination JPEG path
        t: timestamp in seconds (default 1.5 — past the visual hook)
        width: optional scale-to-width (height auto). If None, native size.
        quality: ffmpeg JPEG quality (2 = high, 31 = low). Default 2.
    """
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-ss", str(t), "-i", str(video), "-frames:v", "1"]
    if width is not None:
        cmd += ["-vf", f"scale={width}:-2"]
    cmd += ["-q:v", str(quality), str(out_jpg)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_jpg


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract a single-frame JPEG thumbnail from a video")
    ap.add_argument("video", type=Path)
    ap.add_argument("out_jpg", type=Path)
    ap.add_argument("--t", type=float, default=1.5, help="Seek time in seconds (default 1.5)")
    ap.add_argument("--width", type=int, default=None, help="Optional scale-to-width")
    ap.add_argument("--quality", type=int, default=2, help="JPEG quality 2-31 (lower = better)")
    args = ap.parse_args()

    if not args.video.exists():
        sys.exit(f"video not found: {args.video}")

    out = make_thumbnail(args.video, args.out_jpg, t=args.t, width=args.width, quality=args.quality)
    size_kb = out.stat().st_size / 1024
    print(f"thumbnail: {out} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
