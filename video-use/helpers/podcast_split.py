#!/usr/bin/env python3
"""
Podcast → Reels splitter — turn one long episode into several stand-alone reel
clips, then hand them to the normal batch pipeline.

Flow:
  1. Transcribe the long video (word-level timestamps, via transcribe_one).
  2. Group words into sentences with timestamps.
  3. Ask Claude for the N most reel-worthy, SELF-CONTAINED moments (strong hook,
     makes sense without the rest), each snapped to sentence boundaries.
  4. ffmpeg-extract each segment into raw/batches/<batch>/<seq>-<slug>.mp4.
  5. Print the next step (batch_init --brand ... then the pipeline), or run it
     with --auto.

Each extracted clip is then a normal "raw" — edl_gen still trims filler/versprecher
inside it and the composition adds B-roll + zoom, so segments don't need to be
perfectly cut here, just the right window.

Usage:
    python podcast_split.py --input episode.mp4 --brand default
    python podcast_split.py --input episode.mp4 --brand default --max-clips 8 --min-sec 25 --max-sec 75
    python podcast_split.py --input episode.mp4 --brand default --auto      # also run batch_init + pipeline
    python podcast_split.py --input episode.mp4 --dry-run                          # transcribe + plan, no extraction

Requires OPENAI_API_KEY (Whisper) or ELEVENLABS_API_KEY (--engine scribe) + ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transcribe import transcribe_one, _load_env_key  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HELPERS = Path(__file__).resolve().parent
MODEL_DEFAULT = "claude-opus-4-8"


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:40].rstrip("-")) or "clip"


def sentences_from_words(words: list[dict], *, gap: float = 0.6) -> list[dict]:
    """Group word tokens into sentences (break on .?! or a silence gap)."""
    out: list[dict] = []
    cur: list[dict] = []
    for w in words:
        if w.get("type") not in (None, "word"):
            continue
        txt = (w.get("text") or "").strip()
        if not txt:
            continue
        if cur:
            prev_end = cur[-1].get("end", 0.0)
            if w.get("start", 0.0) - prev_end > gap:
                out.append(_mk_sentence(cur)); cur = []
        cur.append(w)
        if txt[-1] in ".?!…":
            out.append(_mk_sentence(cur)); cur = []
    if cur:
        out.append(_mk_sentence(cur))
    return [s for s in out if s]


def _mk_sentence(words: list[dict]) -> dict | None:
    if not words:
        return None
    text = " ".join((w.get("text") or "").strip() for w in words).strip()
    text = re.sub(r"\s+([.,!?…])", r"\1", text)
    return {"start": round(float(words[0].get("start", 0.0)), 2),
            "end": round(float(words[-1].get("end", 0.0)), 2),
            "text": text}


def transcript_for_llm(sentences: list[dict]) -> str:
    return "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in sentences)


SEG_SCHEMA_HINT = (
    '[{"start": <sec>, "end": <sec>, "title": "<kurzer Titel>", "hook": "<warum stark>"}]'
)


def pick_segments(client, model: str, sentences: list[dict], *,
                  max_clips: int, min_sec: float, max_sec: float, brand: str) -> list[dict]:
    transcript = transcript_for_llm(sentences)
    total = sentences[-1]["end"] if sentences else 0
    system = (
        "Du bist ein Social-Media-Editor. Aus einem langen Podcast-Transkript wählst du die "
        "stärksten EIGENSTÄNDIGEN Momente, die je als kurzes Hochkant-Reel funktionieren. "
        "Ein guter Clip: starker Hook in den ersten Sekunden, ein abgeschlossener Gedanke/Story/"
        "Tipp/Take, versteht sich OHNE den Rest der Folge. Keine Mitten-im-Satz-Schnitte: "
        "Start/Ende MÜSSEN exakt Satz-Zeitstempeln aus der Liste entsprechen."
    )
    user = (
        f"Marke: {brand}. Folgenlänge: {total:.0f}s.\n"
        f"Wähle die {max_clips} besten Clips, jeder zwischen {min_sec:.0f}s und {max_sec:.0f}s lang, "
        f"ohne Überlappung, über die Folge verteilt.\n"
        f"Gib NUR ein JSON-Array zurück, Form: {SEG_SCHEMA_HINT}. "
        f"`start`/`end` in Sekunden, exakt an Satzgrenzen aus dem Transkript.\n\n"
        f"TRANSKRIPT (Satz-Zeitfenster):\n{transcript}"
    )
    resp = client.messages.create(
        model=model, max_tokens=4000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        thinking={"type": "adaptive"},
    )
    text = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise RuntimeError(f"LLM returned no JSON array. Got: {text[:300]}")
    segs = json.loads(m.group(0))

    # Snap each start/end to the nearest sentence boundary + enforce bounds.
    starts = [s["start"] for s in sentences]
    ends = [s["end"] for s in sentences]
    cleaned = []
    for seg in segs:
        st = min(starts, key=lambda x: abs(x - float(seg.get("start", 0))))
        en = min(ends, key=lambda x: abs(x - float(seg.get("end", 0))))
        if en - st < min_sec * 0.6 or en <= st:
            continue
        cleaned.append({"start": st, "end": en,
                        "title": (seg.get("title") or "Clip").strip(),
                        "hook": (seg.get("hook") or "").strip()})
    # Drop overlaps (keep earlier), cap at max_clips.
    cleaned.sort(key=lambda s: s["start"])
    final, last_end = [], -1.0
    for s in cleaned:
        if s["start"] >= last_end:
            final.append(s); last_end = s["end"]
        if len(final) >= max_clips:
            break
    return final


def extract(input_path: Path, seg: dict, out_path: Path) -> bool:
    dur = seg["end"] - seg["start"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-ss", f"{seg['start']:.2f}", "-i", str(input_path), "-t", f"{dur:.2f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out_path),
    ]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Split a long podcast into reel clips for the pipeline.")
    ap.add_argument("--input", required=True, type=Path, help="Long episode video")
    ap.add_argument("--brand", default="default", help="Brand to produce under (default: default)")
    ap.add_argument("--batch", default=None, help="Batch name (default: podcast-<stem>)")
    ap.add_argument("--max-clips", type=int, default=6)
    ap.add_argument("--min-sec", type=float, default=25.0)
    ap.add_argument("--max-sec", type=float, default=75.0)
    ap.add_argument("--engine", default="whisper", choices=["whisper", "scribe"])
    ap.add_argument("--model", default=MODEL_DEFAULT)
    ap.add_argument("--dry-run", action="store_true", help="Transcribe + plan only, no extraction")
    ap.add_argument("--auto", action="store_true", help="After extraction, run batch_init + pipeline")
    args = ap.parse_args()

    inp = args.input.resolve()
    if not inp.exists():
        print(f"ERROR: no such file: {inp}", file=sys.stderr); sys.exit(2)
    if not _load_env_key("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr); sys.exit(2)
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic package required", file=sys.stderr); sys.exit(2)

    batch = args.batch or f"podcast-{_slugify(inp.stem)}"
    print(f"Podcast split: {inp.name} → brand '{args.brand}', batch '{batch}'")

    print("  [1/3] transcribing (this can take a while for a long episode) …")
    tdir = REPO_ROOT / "raw" / "batches" / batch / "_transcribe"
    tpath = transcribe_one(inp, edit_dir=tdir, engine=args.engine, language="de")
    payload = json.loads(Path(tpath).read_text())
    sentences = sentences_from_words(payload.get("words", []))
    if not sentences:
        print("ERROR: empty transcript", file=sys.stderr); sys.exit(1)
    print(f"        {len(sentences)} sentences, {sentences[-1]['end']:.0f}s total")

    print("  [2/3] choosing reel-worthy segments …")
    client = anthropic.Anthropic(api_key=_load_env_key("ANTHROPIC_API_KEY"))
    segs = pick_segments(client, args.model, sentences, max_clips=args.max_clips,
                         min_sec=args.min_sec, max_sec=args.max_sec, brand=args.brand)
    if not segs:
        print("No suitable segments found.", file=sys.stderr); sys.exit(1)
    for i, s in enumerate(segs, 1):
        print(f"        {i:02d}  {s['start']:.0f}-{s['end']:.0f}s ({s['end']-s['start']:.0f}s)  {s['title']}")
        if s.get("hook"):
            print(f"             ↳ {s['hook']}")

    if args.dry_run:
        print("\nDry-run — no clips extracted. Drop --dry-run to cut them.")
        return

    print("  [3/3] extracting clips …")
    batch_dir = REPO_ROOT / "raw" / "batches" / batch
    made = 0
    for i, s in enumerate(segs, 1):
        out = batch_dir / f"{i:02d}-{_slugify(s['title'])}.mp4"
        if extract(inp, s, out):
            print(f"        ✓ {out.relative_to(REPO_ROOT)}")
            made += 1
        else:
            print(f"        ✗ extraction failed for segment {i}")
    print(f"\n{made}/{len(segs)} clips → raw/batches/{batch}/")

    if args.auto and made:
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
