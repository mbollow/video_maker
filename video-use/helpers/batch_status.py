"""Print a status report for one batch (or all batches).

Compact CLI for "where is batch X?" — reads the manifest, shows status
counts per stage, lists per-video status, summarizes scheduled post counts.

Usage:
    python helpers/batch_status.py --batch vertrieb-2026-w22
    python helpers/batch_status.py --batch <name> --verbose
    python helpers/batch_status.py                          # list all batches
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

STAGES = ["transcribed", "edl_planned", "composed", "rendered", "captioned", "scheduled", "posted"]


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text())


def list_all_batches() -> list[Path]:
    batches_dir = REPO_ROOT / "batches"
    if not batches_dir.is_dir():
        return []
    return sorted(p for p in batches_dir.iterdir() if (p / "manifest.json").exists())


def report_one(manifest_path: Path, verbose: bool) -> None:
    manifest = load_manifest(manifest_path)
    batch_name = manifest["batch_name"]
    videos = manifest["videos"]
    tz = ZoneInfo(manifest["common"].get("audience_timezone", "Europe/Berlin"))

    print(f"\n{'=' * 70}")
    print(f"BATCH: {batch_name}")
    print(f"  brand: {manifest.get('brand', 'default')}")
    print(f"  videos: {len(videos)}")
    print(f"  created: {manifest.get('created_at', '?')}")
    print(f"  updated: {manifest.get('updated_at', '?')}")

    # Stage counts
    stage_counts: dict[str, int] = {s: 0 for s in STAGES}
    for v in videos:
        for s in STAGES:
            if v["stages"].get(s):
                stage_counts[s] += 1

    print(f"\n  STAGE PROGRESS ({len(videos)} videos total):")
    for s in STAGES:
        c = stage_counts[s]
        bar = "█" * int(c / max(len(videos), 1) * 20)
        bar += "░" * (20 - len(bar))
        print(f"    {s:14s} {bar} {c}/{len(videos)}")

    # Post status counts
    post_status = Counter()
    for v in videos:
        for platform, post in v["posts"].items():
            if not post.get("enabled"):
                post_status[f"{platform}:disabled"] += 1
            else:
                post_status[f"{platform}:{post.get('status', 'pending')}"] += 1

    print("\n  POST STATUS (enabled platforms only):")
    for platform in ("linkedin", "instagram", "tiktok", "youtube"):
        counts = {k.split(":")[1]: v for k, v in post_status.items() if k.startswith(platform + ":")}
        disabled = counts.pop("disabled", 0)
        pending = counts.pop("pending", 0)
        scheduled = counts.pop("scheduled", 0)
        pushed = counts.pop("pushed", 0)
        failed = counts.pop("failed", 0)
        enabled_total = pending + scheduled + pushed + failed
        if disabled and not enabled_total:
            print(f"    {platform:10s} disabled (OAuth pending)")
        else:
            print(f"    {platform:10s} pending={pending}  scheduled={scheduled}  pushed={pushed}  failed={failed}")

    # Schedule window
    all_times = []
    for v in videos:
        for p, post in v["posts"].items():
            if post.get("scheduled_at"):
                try:
                    all_times.append(datetime.fromisoformat(post["scheduled_at"]).astimezone(tz))
                except Exception:
                    pass
    if all_times:
        all_times.sort()
        print(f"\n  SCHEDULE: {all_times[0].strftime('%d %b %H:%M')} → {all_times[-1].strftime('%d %b %H:%M')} CET ({len(all_times)} posts)")

    if verbose:
        print("\n  PER-VIDEO STATUS:")
        for v in videos:
            status_marks = []
            for s in STAGES:
                done = bool(v["stages"].get(s))
                status_marks.append("✓" if done else "·")
            marks = "".join(status_marks)
            print(f"    {v['seq']:>3s} [{marks}] status={v.get('status','?'):14s} {v.get('slug','')[:40]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Status report for one or all batches")
    ap.add_argument("--batch", default=None, help="Specific batch name (default: list all)")
    ap.add_argument("--verbose", "-v", action="store_true", help="Per-video status details")
    args = ap.parse_args()

    if args.batch:
        manifest_path = REPO_ROOT / "batches" / args.batch / "manifest.json"
        if not manifest_path.exists():
            sys.exit(f"batch not found: {args.batch}")
        report_one(manifest_path, verbose=args.verbose)
    else:
        batches = list_all_batches()
        if not batches:
            print("no batches found")
            return
        for batch_dir in batches:
            report_one(batch_dir / "manifest.json", verbose=args.verbose)


if __name__ == "__main__":
    main()
