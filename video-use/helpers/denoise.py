"""Speech denoise via DeepFilterNet — the standard background-noise removal step.

Replaces the weak ffmpeg `afftdn` filter. DeepFilterNet (RNN speech enhancement)
drops the noise floor by ~30-40 dB on real-world mic noise while keeping the
voice natural, runs on CPU in real time, and is local/free.

Because DeepFilterNet needs a PINNED, isolated environment (it breaks on recent
torch/torchaudio), it lives in its own venv: `video-use/.denoise-venv/`
(torch==2.1.2, torchaudio==2.1.2, soundfile, deepfilternet). Set it up once with
`npm run denoise:setup`. This helper just shells out to that venv's `deepFilter`
CLI, so it can be called from the normal project python.

Usage:
    python helpers/denoise.py --in clips/edited.mp4 --out clips/edited_denoised.wav
    python helpers/denoise.py --in raw.wav --out clean.wav

Then mux the cleaned wav onto the (all-intra) speaker video, e.g.:
    ffmpeg -y -i clips/edited.mp4 -i clips/edited_denoised.wav \
      -map 0:v -map 1:a -c:v libx264 -g 1 -keyint_min 1 -sc_threshold 0 \
      -pix_fmt yuv420p -r 30 -c:a aac -b:a 192k compositions/assets/speaker.mp4
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HELPERS = Path(__file__).resolve().parent
VIDEO_USE = HELPERS.parent
DENOISE_CLI = VIDEO_USE / ".denoise-venv" / "bin" / "deepFilter"


def run(argv: list[str]) -> None:
    p = subprocess.run(argv, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"command failed: {' '.join(argv)}\n{p.stderr[-800:]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Denoise speech audio with DeepFilterNet")
    ap.add_argument("--in", dest="inp", required=True, help="Input media (audio or video)")
    ap.add_argument("--out", required=True, help="Output WAV (denoised, 48k mono)")
    args = ap.parse_args()

    if not DENOISE_CLI.exists():
        sys.exit(
            f"DeepFilterNet venv fehlt: {DENOISE_CLI}\n"
            "Einmalig einrichten mit:  npm run denoise:setup"
        )

    src = Path(args.inp).resolve()
    if not src.exists():
        sys.exit(f"input not found: {src}")
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        wav = td / "in.wav"
        # extract/normalise to 48k mono WAV (DeepFilterNet operates at 48 kHz)
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
             "-vn", "-ac", "1", "-ar", "48000", str(wav)])
        # DeepFilterNet writes <stem>_DeepFilterNet3.wav into the output dir
        run([str(DENOISE_CLI), str(wav), "-o", str(td)])
        produced = td / "in_DeepFilterNet3.wav"
        if not produced.exists():
            cands = list(td.glob("in_DeepFilterNet*.wav"))
            if not cands:
                sys.exit("DeepFilterNet produced no output")
            produced = cands[0]
        shutil.copy2(produced, out)

    print(f"denoised → {out}")


if __name__ == "__main__":
    main()
