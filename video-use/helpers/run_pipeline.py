#!/usr/bin/env python3
"""
Full batch pipeline — chains every stage from "transcribed" to "ready to
review", using the deterministic helpers plus the two headless agents
(edl_gen, compose_gen). Runs a whole batch end-to-end with no Claude in the loop.

Per video:
  1. edl_gen.py            → edl.json                         (headless EDL agent)
  2. render.py edl.json    → clips/edited.mp4 + master.srt    (deterministic cut)
  3. compose_gen.py        → compositions/ + renders/final.mp4 (headless motion agent)
Then per batch:
  4. caption_gen.py        → per-platform captions
  5. schedule_plan.py      → scheduled slots

It deliberately STOPS before pushing to social. The first push is always a
manual draft (Metricool/Postiz) after you review the dashboard — this
orchestrator never publishes.

Usage:
    python run_pipeline.py --batch <name>          # one batch, end-to-end
    python run_pipeline.py --all                   # every batch under batches/
    python run_pipeline.py --batch <name> --dry-run
    python run_pipeline.py --batch <name> --skip caption,schedule

Requires ANTHROPIC_API_KEY (+ OPENAI/ELEVENLABS already used upstream) — the
same .env the rest of the pipeline reads.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HELPERS = Path(__file__).resolve().parent
REPO_ROOT = HELPERS.parent.parent

# Per-video agent/cut stages, in order. (name, is_per_video)
PER_VIDEO = ["edl", "cut", "compose"]
# Batch-level deterministic stages, in order.
PER_BATCH = ["caption", "schedule"]
ALL_STAGES = PER_VIDEO + PER_BATCH


def _run(argv: list[str], *, dry: bool) -> int:
    printable = " ".join(str(a) for a in argv)
    if dry:
        print(f"      DRY-RUN: {printable}")
        return 0
    print(f"      $ {printable}")
    try:
        return subprocess.run(argv, cwd=str(REPO_ROOT)).returncode
    except Exception as e:
        print(f"      ! failed to launch: {e}")
        return 1


def _py(script: str, *args: str) -> list[str]:
    return [sys.executable, str(HELPERS / script), *args]


def process_batch(batch: str, *, skip: set[str], dry: bool) -> bool:
    manifest_path = REPO_ROOT / "batches" / batch / "manifest.json"
    if not manifest_path.exists():
        print(f"[{batch}] no manifest.json — skipping")
        return False
    manifest = json.loads(manifest_path.read_text())
    videos = manifest.get("videos", [])
    print(f"\n=== batch '{batch}': {len(videos)} video(s) ===")

    overall_ok = True

    # --- per-video stages (each agent/helper is idempotent: it skips work
    #     that's already done, so we can safely call once for the whole batch) ---
    if "edl" not in skip:
        print("  [1/5] EDL (headless agent)")
        if _run(_py("edl_gen.py", "--batch", batch), dry=dry) != 0:
            overall_ok = False

    if "cut" not in skip:
        print("  [2/5] apply EDL → cut + subtitles (render.py)")
        for v in videos:
            pdir = REPO_ROOT / v["project_dir"]
            edl = pdir / "edl.json"
            edited = pdir / "clips" / "edited.mp4"
            if not edl.exists():
                print(f"      [{v['seq']}] no edl.json yet — skip cut")
                continue
            if edited.exists():
                print(f"      [{v['seq']}] cut already present")
                continue
            edited.parent.mkdir(parents=True, exist_ok=True)
            # --build-subtitles writes master.srt (the composition's subtitle
            # layer reads it); --no-subtitles keeps them OUT of the cut video so
            # the composition is the ONLY subtitle source (no double subtitles).
            if _run(_py("render.py", str(edl), "-o", str(edited), "--build-subtitles", "--no-subtitles"), dry=dry) != 0:
                overall_ok = False

    if "compose" not in skip:
        print("  [3/5] composition + render (headless agent)")
        if _run(_py("compose_gen.py", "--batch", batch), dry=dry) != 0:
            overall_ok = False

    # --- batch-level deterministic stages ---
    batch_steps = [
        ("caption", 4, _py("caption_gen.py", "--batch", batch)),
        ("schedule", 5, _py("schedule_plan.py", "--batch", batch)),
    ]
    for name, idx, argv in batch_steps:
        if name in skip:
            continue
        print(f"  [{idx}/5] {name}")
        if _run(argv, dry=dry) != 0:
            overall_ok = False

    print(f"=== batch '{batch}': {'OK' if overall_ok else 'completed with errors'} ===")
    print("  NOTE: not pushed. First push is a manual draft after you review "
          f"batches/{batch}/review.html (Metricool or Postiz).")
    return overall_ok


def discover_batches() -> list[str]:
    bdir = REPO_ROOT / "batches"
    if not bdir.exists():
        return []
    return sorted(p.name for p in bdir.iterdir() if p.is_dir() and (p / "manifest.json").exists())


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the full lights-out batch pipeline (transcribed → ready to push).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--batch", help="Single batch name under batches/")
    g.add_argument("--all", action="store_true", help="Process every batch under batches/")
    ap.add_argument("--skip", default="", help=f"Comma-separated stages to skip. Stages: {','.join(ALL_STAGES)}")
    ap.add_argument("--dry-run", action="store_true", help="Print the plan without running anything")
    args = ap.parse_args()

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    bad = skip - set(ALL_STAGES)
    if bad:
        print(f"ERROR: unknown --skip stage(s): {sorted(bad)}. Valid: {ALL_STAGES}", file=sys.stderr)
        sys.exit(2)

    batches = discover_batches() if args.all else [args.batch]
    if not batches:
        print("No batches found.")
        return

    results = {}
    for b in batches:
        results[b] = process_batch(b, skip=skip, dry=args.dry_run)

    print("\n" + "=" * 40)
    for b, ok in results.items():
        print(f"  {b}: {'ok' if ok else 'errors'}")
    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
