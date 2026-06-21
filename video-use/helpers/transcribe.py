"""Transcribe a video — Whisper (primary, OpenAI API) or ElevenLabs Scribe (override).

Extracts mono 16kHz audio via ffmpeg, sends to the chosen engine, writes a
normalized JSON to <edit_dir>/transcripts/<video_stem>.json.

Both engines produce the SAME output shape, so all downstream tooling
(pack_transcripts.py, render.py, etc.) works regardless of engine.

Output JSON schema (engine-agnostic):
    {
      "text": "full transcript text",
      "engine": "whisper" | "scribe",
      "words": [
        {"type": "word", "text": "...", "start": 0.0, "end": 0.42},
        ...
      ]
    }

Cached: if the output file already exists, the upload is skipped.

Usage:
    python helpers/transcribe.py <video_path>                       # default: whisper
    python helpers/transcribe.py <video_path> --engine scribe       # high-quality override
    python helpers/transcribe.py <video_path> --edit-dir /custom/edit
    python helpers/transcribe.py <video_path> --language de
    python helpers/transcribe.py <video_path> --engine scribe --num-speakers 2
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests


SCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"
WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"
WHISPER_MAX_BYTES = 25 * 1024 * 1024  # OpenAI hard limit


def _load_env_key(key_name: str) -> str:
    """Look up an API key in .env files (repo root + cwd) then environment.

    Exits with a clear error message if missing.
    """
    candidates = [
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent.parent.parent / ".env",
        Path(".env"),
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key_name:
                v = v.strip().strip('"').strip("'")
                if v:
                    return v
    v = os.environ.get(key_name, "")
    if v:
        return v
    sys.exit(f"{key_name} not found in .env or environment")


def load_api_key() -> str:
    """Backwards-compatible: returns ELEVENLABS_API_KEY (legacy callers)."""
    return _load_env_key("ELEVENLABS_API_KEY")


def load_openai_key() -> str:
    return _load_env_key("OPENAI_API_KEY")


def load_elevenlabs_key() -> str:
    return _load_env_key("ELEVENLABS_API_KEY")


# -------- Audio extraction ---------------------------------------------------


def extract_audio_wav(video_path: Path, dest: Path) -> None:
    """Extract mono 16kHz PCM WAV. Used by Scribe (lossless preferred)."""
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(dest),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def extract_audio_mp3(video_path: Path, dest: Path, bitrate: str = "64k") -> None:
    """Extract mono MP3 to stay safely under OpenAI's 25MB limit.

    64kbps mono = ~480KB/min → 50 minutes fits in 25MB.
    """
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "libmp3lame", "-b:a", bitrate,
        str(dest),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# -------- Whisper (OpenAI) ---------------------------------------------------


def call_whisper(
    audio_path: Path,
    api_key: str,
    language: str | None = None,
    vocab_prompt: str | None = None,
) -> dict:
    """Call OpenAI Whisper API with word-level timestamps.

    Args:
        vocab_prompt: optional bias string (max ~224 tokens) to nudge
          recognition of domain-specific terms. Critical for German content
          with brand/jargon (e.g. "Kaltakquise" otherwise becomes "kalter Kiesel").
    """
    data: dict[str, object] = {
        "model": "whisper-1",
        "response_format": "verbose_json",
        "timestamp_granularities[]": "word",
    }
    if language:
        data["language"] = language
    if vocab_prompt:
        data["prompt"] = vocab_prompt

    with open(audio_path, "rb") as f:
        resp = requests.post(
            WHISPER_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (audio_path.name, f, "audio/mpeg")},
            data=data,
            timeout=600,
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Whisper returned {resp.status_code}: {resp.text[:500]}")

    return resp.json()


def normalize_whisper(payload: dict) -> dict:
    """Map Whisper's response to the engine-agnostic schema."""
    words_in = payload.get("words") or []
    words_out = []
    for w in words_in:
        text = w.get("word", "").strip()
        if not text:
            continue
        words_out.append({
            "type": "word",
            "text": text,
            "start": float(w.get("start", 0.0)),
            "end": float(w.get("end", 0.0)),
        })
    return {
        "text": payload.get("text", "").strip(),
        "engine": "whisper",
        "words": words_out,
        "language": payload.get("language"),
        "duration": payload.get("duration"),
    }


# -------- Scribe (ElevenLabs) ------------------------------------------------


def call_scribe(
    audio_path: Path,
    api_key: str,
    language: str | None = None,
    num_speakers: int | None = None,
) -> dict:
    data: dict[str, str] = {
        "model_id": "scribe_v1",
        "diarize": "true",
        "tag_audio_events": "true",
        "timestamps_granularity": "word",
    }
    if language:
        data["language_code"] = language
    if num_speakers:
        data["num_speakers"] = str(num_speakers)

    with open(audio_path, "rb") as f:
        resp = requests.post(
            SCRIBE_URL,
            headers={"xi-api-key": api_key},
            files={"file": (audio_path.name, f, "audio/wav")},
            data=data,
            timeout=1800,
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Scribe returned {resp.status_code}: {resp.text[:500]}")

    return resp.json()


def normalize_scribe(payload: dict) -> dict:
    """Tag Scribe's response with engine and pass through (already correct shape)."""
    payload = dict(payload)
    payload["engine"] = "scribe"
    # Scribe already uses {"type": "word"|"spacing"|"audio_event", "text", "start", "end"}
    return payload


# -------- Unified dispatch ---------------------------------------------------


def transcribe_one(
    video: Path,
    edit_dir: Path,
    engine: str = "whisper",
    language: str | None = None,
    num_speakers: int | None = None,
    vocab_prompt: str | None = None,
    verbose: bool = True,
    # Legacy compat: callers that pass api_key (Scribe-only callers)
    api_key: str | None = None,
) -> Path:
    """Transcribe a single video. Returns path to transcript JSON.

    Cached: returns existing path immediately if the transcript already exists.
    """
    transcripts_dir = edit_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    out_path = transcripts_dir / f"{video.stem}.json"

    if out_path.exists():
        if verbose:
            print(f"cached: {out_path.name}")
        return out_path

    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        if engine == "whisper":
            audio = Path(tmp) / f"{video.stem}.mp3"
            if verbose:
                print(f"  [whisper] extracting audio from {video.name}", flush=True)
            extract_audio_mp3(video, audio)
            size_mb = audio.stat().st_size / (1024 * 1024)
            if audio.stat().st_size > WHISPER_MAX_BYTES:
                raise RuntimeError(
                    f"audio too large for Whisper API ({size_mb:.1f} MB > 25 MB). "
                    f"Lower bitrate or chunk the video first."
                )
            if verbose:
                print(f"  [whisper] uploading {audio.name} ({size_mb:.1f} MB)", flush=True)
            key = api_key or load_openai_key()
            raw = call_whisper(audio, key, language=language, vocab_prompt=vocab_prompt)
            payload = normalize_whisper(raw)

        elif engine == "scribe":
            audio = Path(tmp) / f"{video.stem}.wav"
            if verbose:
                print(f"  [scribe] extracting audio from {video.name}", flush=True)
            extract_audio_wav(video, audio)
            size_mb = audio.stat().st_size / (1024 * 1024)
            if verbose:
                print(f"  [scribe] uploading {audio.name} ({size_mb:.1f} MB)", flush=True)
            key = api_key or load_elevenlabs_key()
            raw = call_scribe(audio, key, language=language, num_speakers=num_speakers)
            payload = normalize_scribe(raw)

        else:
            raise ValueError(f"unknown engine: {engine!r} (use 'whisper' or 'scribe')")

    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    dt = time.time() - t0

    if verbose:
        kb = out_path.stat().st_size / 1024
        n_words = sum(1 for w in payload.get("words", []) if w.get("type") == "word")
        print(f"  [{engine}] saved: {out_path.name} ({kb:.1f} KB) in {dt:.1f}s — {n_words} words")

    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Transcribe a video — Whisper (default) or Scribe")
    ap.add_argument("video", type=Path, help="Path to video file")
    ap.add_argument(
        "--engine",
        choices=["whisper", "scribe"],
        default="whisper",
        help="Transcription engine (default: whisper — cheaper, batch-friendly). "
             "Use 'scribe' for higher-quality single-project work.",
    )
    ap.add_argument(
        "--edit-dir",
        type=Path,
        default=None,
        help="Edit output directory (default: <video_parent>/edit)",
    )
    ap.add_argument(
        "--language",
        type=str,
        default=None,
        help="Optional ISO language code (e.g., 'de', 'en'). Omit to auto-detect.",
    )
    ap.add_argument(
        "--num-speakers",
        type=int,
        default=None,
        help="(Scribe only) Number of speakers when known. Improves diarization.",
    )
    ap.add_argument(
        "--vocab-prompt",
        type=str,
        default=None,
        help="(Whisper only) Vocabulary bias prompt (max ~224 tokens). "
             "Useful for brand-specific terms and proper nouns Whisper mishears. "
             "Example: a comma-separated list of your recurring names, product "
             "names and technical terms.",
    )
    args = ap.parse_args()

    video = args.video.resolve()
    if not video.exists():
        sys.exit(f"video not found: {video}")

    edit_dir = (args.edit_dir or (video.parent / "edit")).resolve()

    transcribe_one(
        video=video,
        edit_dir=edit_dir,
        engine=args.engine,
        language=args.language,
        num_speakers=args.num_speakers,
        vocab_prompt=args.vocab_prompt,
    )


if __name__ == "__main__":
    main()
