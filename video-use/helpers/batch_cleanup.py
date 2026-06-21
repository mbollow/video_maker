"""Storage rotation for batches.

At 30-50 videos/day, raw + intermediate files accumulate quickly (~75 GB/mo).
This helper deletes old artifacts while preserving the audit trail.

WHAT GETS DELETED (after --older-than-days threshold):
- raw/batches/<batch>/*.mp4          (source files, biggest disk-hog)
- projects/<batch>__<seq>/clips/     (intermediate cut + base.mp4)
- projects/<batch>__<seq>/previews/  (preview renders)
- projects/<batch>__<seq>/_bundle_assets/ (if any)
- projects/<batch>__<seq>/clips_graded/ (per-segment extracts)
- projects/<batch>__<seq>/compositions/assets/speaker.mp4 (keyframe-converted)
- /tmp/_throwaway_*

WHAT GETS KEPT:
- batches/<batch>/manifest.json        (audit trail, source of truth)
- batches/<batch>/review.html          (review snapshot)
- batches/<batch>/thumbnails/          (small JPGs, useful for retrospectives)
- batches/<batch>/postiz/              (push logs + responses)
- projects/<batch>__<seq>/renders/     (final.mp4 — the actual output)
- projects/<batch>__<seq>/transcripts/ (.json, tiny)
- projects/<batch>__<seq>/edl.json     (cut decisions)
- projects/<batch>__<seq>/takes_packed.md
- projects/<batch>__<seq>/master.srt
- projects/<batch>__<seq>/compositions/index.html (no assets)

Default is --dry-run; pass --apply to actually delete.

Usage:
    python helpers/batch_cleanup.py --older-than-days 14                    # dry-run
    python helpers/batch_cleanup.py --older-than-days 14 --apply            # do it
    python helpers/batch_cleanup.py --batch <name> --apply                  # one batch only
    python helpers/batch_cleanup.py --all --apply                           # all batches
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Per-project subdirs/files that are intermediates and safe to delete
PROJECT_DISPOSABLE_DIRS = ["clips", "previews", "_bundle_assets", "clips_graded", "clips_draft", "clips_preview", "verify"]
PROJECT_DISPOSABLE_FILES = ["base.mp4", "compositions/assets/speaker.mp4"]


def now() -> datetime:
    return datetime.now(timezone.utc)


def load_manifest(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def batch_age_days(manifest_path: Path) -> float:
    m = load_manifest(manifest_path)
    if not m:
        # Fall back to file mtime
        return (now() - datetime.fromtimestamp(manifest_path.stat().st_mtime, tz=timezone.utc)).days
    iso = m.get("updated_at") or m.get("created_at")
    if not iso:
        return 0.0
    try:
        dt = datetime.fromisoformat(iso)
        return (now() - dt).total_seconds() / 86400.0
    except Exception:
        return 0.0


def dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except (OSError, FileNotFoundError):
                pass
    return total


def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def collect_targets(batch_name: str, manifest: dict) -> list[tuple[Path, str]]:
    """Return list of (path, reason) for things that would be deleted."""
    targets: list[tuple[Path, str]] = []

    # 1. Raw videos for this batch
    raw_dir = REPO_ROOT / "raw" / "batches" / batch_name
    if raw_dir.exists():
        for f in raw_dir.iterdir():
            if f.is_file():
                targets.append((f, "raw"))

    # 2. Per-project intermediates
    for v in manifest.get("videos", []):
        project_dir = REPO_ROOT / v["project_dir"]
        if not project_dir.exists():
            continue
        for sub in PROJECT_DISPOSABLE_DIRS:
            p = project_dir / sub
            if p.exists() and p.is_dir():
                targets.append((p, "intermediate-dir"))
        for f in PROJECT_DISPOSABLE_FILES:
            p = project_dir / f
            if p.exists() and p.is_file():
                targets.append((p, "intermediate-file"))

    return targets


def cleanup_batch(batch_name: str, apply: bool) -> tuple[int, int]:
    """Returns (n_items, total_bytes_freed)."""
    manifest_path = REPO_ROOT / "batches" / batch_name / "manifest.json"
    manifest = load_manifest(manifest_path)
    if not manifest:
        print(f"  ! {batch_name}: no manifest, skipping")
        return 0, 0

    targets = collect_targets(batch_name, manifest)
    total_bytes = 0
    for p, _ in targets:
        if p.is_file():
            total_bytes += p.stat().st_size
        else:
            total_bytes += dir_size_bytes(p)

    print(f"  • {batch_name}: {len(targets)} items, {fmt_bytes(total_bytes)} reclaimable")
    if not apply:
        for p, reason in targets[:5]:
            print(f"    [{reason}] {p.relative_to(REPO_ROOT)}")
        if len(targets) > 5:
            print(f"    ... and {len(targets) - 5} more")
        return len(targets), total_bytes

    # Actually delete
    deleted = 0
    for p, reason in targets:
        try:
            if p.is_file():
                p.unlink()
            else:
                shutil.rmtree(p)
            deleted += 1
        except Exception as e:
            print(f"    ! failed to delete {p}: {e}")
    print(f"    + deleted {deleted}/{len(targets)} items")
    return deleted, total_bytes


def main() -> None:
    ap = argparse.ArgumentParser(description="Storage rotation for VideoMaker batches")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--batch", help="Clean up a specific batch")
    g.add_argument("--all", action="store_true", help="Clean up all batches that match age threshold")
    ap.add_argument("--older-than-days", type=float, default=14.0,
                    help="Only clean batches older than this (default 14)")
    ap.add_argument("--apply", action="store_true",
                    help="Actually delete (default is --dry-run)")
    args = ap.parse_args()

    if not args.batch and not args.all:
        ap.error("specify --batch <name> or --all")

    if args.batch:
        batches = [args.batch]
    else:
        batches_root = REPO_ROOT / "batches"
        if not batches_root.exists():
            print("no batches/ directory")
            return
        batches = []
        for d in sorted(batches_root.iterdir()):
            mp = d / "manifest.json"
            if not mp.exists():
                continue
            age = batch_age_days(mp)
            if age >= args.older_than_days:
                batches.append(d.name)
        if not batches:
            print(f"no batches older than {args.older_than_days} days")
            return

    print(f"{'dry-run: ' if not args.apply else ''}cleanup for {len(batches)} batch(es)")
    if not args.apply:
        print("(re-run with --apply to actually delete)\n")
    else:
        print()

    total_items = 0
    total_bytes = 0
    for batch_name in batches:
        n, b = cleanup_batch(batch_name, args.apply)
        total_items += n
        total_bytes += b

    print(f"\n{'reclaimable' if not args.apply else 'reclaimed'}: {total_items} items, {fmt_bytes(total_bytes)}")


if __name__ == "__main__":
    main()
