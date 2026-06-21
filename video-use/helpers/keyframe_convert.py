#!/usr/bin/env python3
"""All-intra keyframe conversion for HyperFrames speaker.mp4.

Why: Hyperframes sets `video.currentTime = t` per frame during render. Without
all-intra encoding, the seek snaps to the nearest keyframe (often 4-10 second
intervals) and the speaker appears frozen.

Usage:
    python video-use/helpers/keyframe_convert.py <input.mp4> <output.mp4>
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def convert(src: Path, dst: Path) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-g", "1", "-keyint_min", "1", "-sc_threshold", "0",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "192k",
        str(dst),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-2000:] + "\n")
    return r.returncode


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: keyframe_convert.py <input.mp4> <output.mp4>")
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    rc = convert(src, dst)
    if rc == 0:
        size_mb = dst.stat().st_size / (1024 * 1024)
        print(f"OK: wrote {dst} ({size_mb:.1f} MiB)")
    sys.exit(rc)


if __name__ == "__main__":
    main()
