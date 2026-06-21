"""Deterministic schedule allocator for a batch.

For each video × each enabled platform, picks the next available slot from
the preferred_slots_cet windows defined in manifest.schedule_strategy.

Constraints:
- max_per_platform_per_day not exceeded
- min_hours_between_same_platform respected
- No two platforms post in the exact same minute (5min offset on collision)
- For the SAME video: LinkedIn slot must come BEFORE Instagram slot
  (DACH B2B pattern: LinkedIn discovers, IG/TikTok amplify)
- Slots that are locked (scheduled_at_locked = true) are not modified

Times are stored as ISO 8601 with Europe/Berlin timezone.

Usage:
    python helpers/schedule_plan.py --batch vertrieb-2026-w22
    python helpers/schedule_plan.py --batch <name> --start 2026-05-27
    python helpers/schedule_plan.py --batch <name> --window-days 30
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

WEEKDAY_MAP = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text())


def save_manifest(path: Path, manifest: dict) -> None:
    manifest["updated_at"] = now_iso()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    os.replace(tmp, path)
    _maybe_sync_to_web(path.parent.name)


def _maybe_sync_to_web(batch_name: str) -> None:
    """Fire-and-forget push of the manifest to the web app. Silent on failure."""
    if not os.environ.get("VIDEOMAKER_WEB_URL"):
        return
    sync_script = Path(__file__).resolve().parent / "batch_sync.py"
    if not sync_script.exists():
        return
    try:
        subprocess.run(
            [sys.executable, str(sync_script), "--batch", batch_name],
            check=False, capture_output=True, timeout=15,
        )
    except Exception:
        pass


def parse_slot_spec(spec: str) -> tuple[int, int, int]:
    """Parse 'Tue 07:45' → (weekday=1, hour=7, minute=45)."""
    weekday_str, time_str = spec.split(" ", 1)
    weekday = WEEKDAY_MAP[weekday_str]
    hour, minute = (int(x) for x in time_str.split(":"))
    return weekday, hour, minute


def generate_slot_candidates(
    *,
    start_date: datetime,
    window_days: int,
    preferred_slots_cet: dict[str, list[str]],
    tz: ZoneInfo,
) -> dict[str, list[datetime]]:
    """Materialize concrete datetime candidates per platform in the window."""
    out: dict[str, list[datetime]] = {}
    end_date = start_date + timedelta(days=window_days)
    for platform, slot_specs in preferred_slots_cet.items():
        candidates: list[datetime] = []
        parsed = [parse_slot_spec(s) for s in slot_specs]
        # Walk every day in the window
        day = start_date
        while day < end_date:
            for weekday, hour, minute in parsed:
                if day.weekday() == weekday:
                    slot = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
                    if slot >= start_date:
                        candidates.append(slot)
            day += timedelta(days=1)
        candidates.sort()
        out[platform] = candidates
    return out


def allocate_slots(
    *,
    manifest: dict,
    start_date: datetime | None = None,
    window_days: int | None = None,
    tz: ZoneInfo = ZoneInfo("Europe/Berlin"),
) -> int:
    """Mutates manifest in place. Returns number of slots assigned."""
    strat = manifest["schedule_strategy"]
    if start_date is None:
        if strat.get("start_date"):
            start_date = datetime.fromisoformat(strat["start_date"]).astimezone(tz)
        else:
            # Default: next Tuesday at 00:00 CET
            now = datetime.now(tz)
            days_until_tue = (1 - now.weekday()) % 7 or 7
            start_date = (now + timedelta(days=days_until_tue)).replace(hour=0, minute=0, second=0, microsecond=0)
    if window_days is None:
        window_days = strat.get("window_days", 14)

    # Persist back
    strat["start_date"] = start_date.date().isoformat()
    strat["window_days"] = window_days

    candidates = generate_slot_candidates(
        start_date=start_date,
        window_days=window_days,
        preferred_slots_cet=strat["preferred_slots_cet"],
        tz=tz,
    )

    max_per_day = strat.get("max_per_platform_per_day", 4)
    min_gap_hours = strat.get("min_hours_between_same_platform", 4)
    min_gap = timedelta(hours=min_gap_hours)

    # Track per-platform usage
    used: dict[str, list[datetime]] = {p: [] for p in candidates}

    def slot_available(platform: str, slot: datetime) -> bool:
        # Count same-day uses
        same_day = sum(1 for u in used[platform] if u.date() == slot.date())
        if same_day >= max_per_day:
            return False
        # Min-gap check
        for u in used[platform]:
            if abs((slot - u).total_seconds()) < min_gap.total_seconds():
                return False
        return True

    def find_next_slot(platform: str, after: datetime | None = None) -> datetime | None:
        for cand in candidates.get(platform, []):
            if after is not None and cand < after:
                continue
            if slot_available(platform, cand):
                return cand
        return None

    def has_minute_collision(slot: datetime) -> bool:
        """Returns True if ANY platform already uses this exact (date, hour, minute)."""
        for plat_uses in used.values():
            for u in plat_uses:
                if u == slot:
                    return True
        return False

    def offset_to_avoid_collision(slot: datetime) -> datetime:
        candidate = slot
        for _ in range(20):  # max 20 minutes of offset attempts
            if not has_minute_collision(candidate):
                return candidate
            candidate += timedelta(minutes=5)
        return candidate  # give up, just use it anyway

    assigned = 0
    for v in manifest["videos"]:
        # LinkedIn first (DACH B2B amplification pattern)
        linkedin_slot: datetime | None = None
        platforms_in_order = ["linkedin", "instagram", "tiktok", "youtube"]
        for platform in platforms_in_order:
            post = v["posts"].get(platform)
            if not post or not post.get("enabled"):
                continue
            if post.get("scheduled_at_locked") and post.get("scheduled_at"):
                # Keep user-locked schedule, still count it as "used"
                used[platform].append(datetime.fromisoformat(post["scheduled_at"]))
                if platform == "linkedin":
                    linkedin_slot = datetime.fromisoformat(post["scheduled_at"])
                continue
            after = linkedin_slot if platform != "linkedin" else None
            slot = find_next_slot(platform, after=after)
            if slot is None:
                print(f"  ! no slot available for video {v['seq']} platform {platform}")
                continue
            slot = offset_to_avoid_collision(slot)
            post["scheduled_at"] = slot.isoformat()
            post["status"] = "scheduled"
            used[platform].append(slot)
            if platform == "linkedin":
                linkedin_slot = slot
            assigned += 1
        # Mark stage
        v["stages"]["scheduled"] = {"at": now_iso()}
        if v.get("status") in ("captioned", "rendered", "scheduled"):
            v["status"] = "scheduled"

    return assigned


def main() -> None:
    ap = argparse.ArgumentParser(description="Allocate schedule slots for a batch")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--start", default=None, help="Start date YYYY-MM-DD (default: next Tuesday)")
    ap.add_argument("--window-days", type=int, default=None)
    ap.add_argument("--tz", default="Europe/Berlin")
    args = ap.parse_args()

    manifest_path = REPO_ROOT / "batches" / args.batch / "manifest.json"
    manifest = load_manifest(manifest_path)
    tz = ZoneInfo(args.tz)

    start_date = None
    if args.start:
        start_date = datetime.fromisoformat(args.start).replace(tzinfo=tz)

    n = allocate_slots(
        manifest=manifest,
        start_date=start_date,
        window_days=args.window_days,
        tz=tz,
    )
    save_manifest(manifest_path, manifest)

    print(f"assigned {n} slots across {len(manifest['videos'])} videos")
    if n > 0:
        strat = manifest["schedule_strategy"]
        print(f"  window: {strat['start_date']} + {strat['window_days']} days")
        print(f"  manifest: {manifest_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
