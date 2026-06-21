"""Apply Phase-7 correction shorthand to a batch manifest.

Reads correction lines (from stdin or a file) and mutates the manifest.
Each line targets ONE video by its 2-digit sequence, then specifies an
action.

Supported shorthand:

    01: skip                      → all platforms disabled for video 01
    03: skip tiktok               → tiktok disabled for video 03
    07: linkedin 2026-05-28 09:15 → reschedule linkedin for video 07 to that time
    07: instagram Mi 19:30        → reschedule instagram for video 07 to next Mi 19:30 CET
    12: re-cut                    → mark video 12 for EDL re-generation (resets stages)
    12: re-cut shorter            → re-cut with directive "shorter" stored as user_correction
    05: re-caption                → reset caption stage so caption_gen reruns
    05: re-render                 → reset compose/render stages
    08: enable tiktok             → enable previously-disabled platform
    08: caption linkedin "Neuer Hook..." → manually override LinkedIn caption

Time-shorthand formats:
    Full ISO:   2026-05-28T09:15
    ISO date:   2026-05-28 09:15  (treated as CET)
    Weekday:    Mo|Di|Mi|Do|Fr|Sa|So  HH:MM  (next occurrence)
    English:    Mon|Tue|Wed|Thu|Fri|Sat|Sun HH:MM

Usage:
    echo "03: skip tiktok" | python helpers/apply_corrections.py --batch <name>
    python helpers/apply_corrections.py --batch <name> --file corrections.txt
    python helpers/apply_corrections.py --batch <name> --dry-run --file corrections.txt
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

WEEKDAY_DE = {"Mo": 0, "Di": 1, "Mi": 2, "Do": 3, "Fr": 4, "Sa": 5, "So": 6}
WEEKDAY_EN = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
WEEKDAY_ALL = {**WEEKDAY_DE, **WEEKDAY_EN}

PLATFORMS = {"linkedin", "instagram", "tiktok", "youtube"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text())


def save_manifest(path: Path, manifest: dict) -> None:
    manifest["updated_at"] = now_iso()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    os.replace(tmp, path)
    _maybe_sync_to_web(path.parent.name)


def _maybe_sync_to_web(batch_name: str) -> None:
    """Fire-and-forget push of the manifest to the web app. Silent on failure —
    the on-disk manifest is the source of truth and `npm run batch:sync` can retry."""
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


def parse_time_token(token_parts: list[str], tz: ZoneInfo) -> str | None:
    """Try to parse a time spec from the last 1-3 tokens. Returns ISO 8601 string."""
    if not token_parts:
        return None
    joined = " ".join(token_parts)

    # Full ISO
    try:
        dt = datetime.fromisoformat(joined.replace(" ", "T", 1))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.isoformat()
    except ValueError:
        pass

    # Weekday + HH:MM
    parts = joined.split()
    if len(parts) == 2 and parts[0] in WEEKDAY_ALL:
        target_weekday = WEEKDAY_ALL[parts[0]]
        try:
            hour, minute = (int(x) for x in parts[1].split(":"))
        except (ValueError, IndexError):
            return None
        now = datetime.now(tz)
        days_until = (target_weekday - now.weekday()) % 7
        if days_until == 0 and (now.hour, now.minute) >= (hour, minute):
            days_until = 7
        dt = (now + timedelta(days=days_until)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        return dt.isoformat()

    return None


def find_video(manifest: dict, seq: str) -> dict | None:
    for v in manifest["videos"]:
        if v["seq"] == seq:
            return v
    return None


def reset_stages_from(video: dict, *stages: str) -> None:
    """Set listed stages to None so they re-run, also downgrade status."""
    stage_order = ["transcribed", "edl_planned", "composed", "rendered", "captioned", "scheduled", "posted"]
    earliest = min((stage_order.index(s) for s in stages if s in stage_order), default=None)
    if earliest is None:
        return
    for i, s in enumerate(stage_order):
        if i >= earliest:
            video["stages"][s] = None
    # Recompute status: the latest non-None stage
    new_status = "created"
    for s in stage_order:
        if video["stages"].get(s):
            new_status = s
    video["status"] = new_status


def apply_one(manifest: dict, raw_line: str, tz: ZoneInfo) -> str:
    """Apply ONE correction line. Returns a human-readable summary."""
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return ""

    # Format: "<seq>: <action and args>"
    m = re.match(r"^(\d{1,3})\s*:\s*(.+)$", line)
    if not m:
        return f"  ! ignored (no seq): {line}"
    seq = m.group(1).zfill(2)
    rest = m.group(2).strip()

    video = find_video(manifest, seq)
    if not video:
        return f"  ! ignored (seq {seq} not in batch): {line}"

    parts = rest.split()
    action = parts[0].lower()

    # Direct "caption <platform> "<text>"" pattern (quoted multi-word caption)
    cap_match = re.match(r"^caption\s+(linkedin|instagram|tiktok|youtube)\s+\"(.+)\"$", rest, re.IGNORECASE)
    if cap_match:
        platform = cap_match.group(1).lower()
        new_caption = cap_match.group(2)
        video["posts"][platform]["caption"] = new_caption
        video["user_corrections"].append({"at": now_iso(), "action": "caption-override", "platform": platform})
        return f"  + {seq}: caption {platform} overridden ({len(new_caption)} chars)"

    if action == "skip":
        if len(parts) == 1:
            # Skip entire video on ALL platforms
            for p in PLATFORMS:
                video["posts"][p]["enabled"] = False
            video["user_corrections"].append({"at": now_iso(), "action": "skip-all"})
            return f"  + {seq}: skip ALL platforms"
        elif parts[1].lower() in PLATFORMS:
            platform = parts[1].lower()
            video["posts"][platform]["enabled"] = False
            video["user_corrections"].append({"at": now_iso(), "action": f"skip-{platform}"})
            return f"  + {seq}: skip {platform}"

    if action == "enable" and len(parts) >= 2 and parts[1].lower() in PLATFORMS:
        platform = parts[1].lower()
        video["posts"][platform]["enabled"] = True
        video["user_corrections"].append({"at": now_iso(), "action": f"enable-{platform}"})
        return f"  + {seq}: enable {platform}"

    # Platform <time> → reschedule
    if action in PLATFORMS:
        platform = action
        time_iso = parse_time_token(parts[1:], tz)
        if time_iso:
            video["posts"][platform]["scheduled_at"] = time_iso
            video["posts"][platform]["scheduled_at_locked"] = True
            video["posts"][platform]["status"] = "scheduled"
            video["user_corrections"].append({"at": now_iso(), "action": f"reschedule-{platform}", "time": time_iso})
            return f"  + {seq}: {platform} → {time_iso}"
        return f"  ! {seq}: could not parse time in '{rest}'"

    if action == "re-cut":
        directive = " ".join(parts[1:]) if len(parts) > 1 else None
        reset_stages_from(video, "edl_planned", "composed", "rendered", "captioned", "scheduled")
        video["user_corrections"].append({"at": now_iso(), "action": "re-cut", "directive": directive})
        return f"  + {seq}: re-cut queued ({directive or 'no directive'})"

    if action == "re-render":
        reset_stages_from(video, "composed", "rendered", "captioned")
        video["user_corrections"].append({"at": now_iso(), "action": "re-render"})
        return f"  + {seq}: re-render queued"

    if action == "re-caption":
        reset_stages_from(video, "captioned")
        video["user_corrections"].append({"at": now_iso(), "action": "re-caption"})
        return f"  + {seq}: re-caption queued"

    return f"  ! {seq}: unknown action '{action}' — see helper docstring"


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply Phase-7 correction shorthand to a batch manifest")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--file", type=Path, default=None, help="Read corrections from file (default: stdin)")
    ap.add_argument("--dry-run", action="store_true", help="Print actions without mutating manifest")
    args = ap.parse_args()

    batch_dir = REPO_ROOT / "batches" / args.batch
    manifest_path = batch_dir / "manifest.json"
    if not manifest_path.exists():
        sys.exit(f"manifest not found: {manifest_path}")

    manifest = load_manifest(manifest_path)
    tz = ZoneInfo(manifest["common"].get("audience_timezone", "Europe/Berlin"))

    if args.file:
        lines = args.file.read_text().splitlines()
    else:
        print("Paste correction lines (Ctrl-D when done):")
        lines = sys.stdin.read().splitlines()

    print(f"\napplying corrections to batch {args.batch}:")
    n_applied = 0
    for line in lines:
        summary = apply_one(manifest, line, tz)
        if summary:
            print(summary)
            if summary.lstrip().startswith("+"):
                n_applied += 1

    if not args.dry_run and n_applied > 0:
        save_manifest(manifest_path, manifest)
        print(f"\n{n_applied} corrections applied to {manifest_path.relative_to(REPO_ROOT)}")
    elif args.dry_run:
        print(f"\n[dry-run] would have applied {n_applied} corrections")
    else:
        print("\nno corrections applied")


if __name__ == "__main__":
    main()
