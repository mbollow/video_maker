"""Push a single video as a GoHighLevel social planner post (draft by default).

Uploads the rendered MP4 to the GHL Media Library, then creates a social
planner post for one or more connected accounts. Defaults to DRAFT — the post
shows up in the GHL Social Planner for review and is NOT published.

This is the GHL counterpart to postiz_push.py, kept deliberately parallel so
Postiz/Metricool stay untouched while we evaluate GHL.

Usage (single test post as draft on one account):
    python helpers/ghl_push.py \
        --video "/path/to/final_v3.mp4" \
        --caption-file "/path/to/captions.txt" \
        --caption-section LINKEDIN \
        --account-id "687b..._page"

    # multiple accounts: repeat --account-id
    # go live on a schedule instead of draft:
    #   --status scheduled --schedule-date 2026-07-01T09:15:00+02:00

Env (.env): GHL_PRIVATE_INTEGRATION_TOKEN, GHL_LOCATION_ID
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import brand_text  # noqa: E402
from transcribe import _load_env_key  # noqa: E402
from ghl_client import GHLClient, GHLError  # noqa: E402
from ghl_schedule import (  # noqa: E402
    BERLIN, WEEKDAY_NAMES, next_free_slots, parse_time, parse_weekdays,
)
from ghl_ledger import (  # noqa: E402
    LEDGER_PATH, append_entry, entries_for, load_ledger,
    published_accounts_for, sha256_file,
)


def _load_env_key_optional(name: str) -> str | None:
    """Like _load_env_key but returns None instead of exiting when missing."""
    try:
        return _load_env_key(name)
    except SystemExit:
        return None


# Platform -> caption section(s) to try, in order. Our captions files only have
# LINKEDIN and INSTAGRAM blocks. Facebook has no own block and falls back to the
# INSTAGRAM text (Facebook + Instagram are both Meta and treated as equal,
# informal networks — NOT the formal LinkedIn copy). See memory
# ghl-facebook-uses-instagram-caption.
PLATFORM_SECTIONS = {
    "linkedin": ["LINKEDIN"],
    "instagram": ["INSTAGRAM"],
    "facebook": ["FACEBOOK", "INSTAGRAM"],
    "google": ["GOOGLE", "INSTAGRAM"],
}


def _extract_caption_section(text: str, section: str | None) -> str | None:
    """Pull one platform block out of a captions file.

    Blocks are delimited by a line of '=' followed by an uppercase platform name
    (e.g. LINKEDIN, INSTAGRAM). Returns the whole stripped text when `section` is
    None; returns None when the requested section is not present.
    """
    if not section:
        return text.strip()
    lines = text.splitlines()
    target = section.strip().upper()
    collected: list[str] = []
    capturing = False
    for i, line in enumerate(lines):
        header = line.strip().upper()
        is_sep = set(line.strip()) == {"="} and line.strip() != ""
        if header == target and not is_sep:
            capturing = True
            continue
        if capturing:
            # stop at the next platform header (separated by '=' lines)
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if set(line.strip()) == {"="} and nxt and nxt.upper() != target and nxt.isupper():
                break
            collected.append(line)
    if not capturing:
        return None
    block = "\n".join(collected).strip("=").strip()
    return block or None


def resolve_caption(raw_text: str, platform: str, override_section: str | None) -> str:
    """Pick the caption for a platform: explicit override, else by-platform block.

    Letzte Station vor dem Upload — deshalb laufen hier die Marken-Textregeln
    (u.a. #PalstekGmbH statt #Palstek) noch einmal drueber, egal aus welcher
    Pipeline oder handgepflegten captions.txt der Text kommt.
    """
    if override_section:
        block = _extract_caption_section(raw_text, override_section)
        return brand_text.fix_hashtags(block if block else raw_text.strip())
    for sec in PLATFORM_SECTIONS.get(platform, ["LINKEDIN"]):
        block = _extract_caption_section(raw_text, sec)
        if block:
            return brand_text.fix_hashtags(block)
    return brand_text.fix_hashtags(raw_text.strip())


def main() -> None:
    ap = argparse.ArgumentParser(description="Push one video to GHL social planner")
    ap.add_argument("--video", required=True, help="Path to the rendered MP4")
    ap.add_argument("--caption", help="Caption text (inline)")
    ap.add_argument("--caption-file", help="Path to a captions .txt file")
    ap.add_argument("--caption-section",
                    help="Platform block to extract from the captions file "
                         "(e.g. LINKEDIN, INSTAGRAM)")
    ap.add_argument("--account-id", action="append", default=[], dest="account_ids",
                    help="GHL social account id (repeat for multiple)")
    ap.add_argument("--status", choices=["draft", "scheduled", "published"],
                    default="draft", help="Post status (default: draft)")
    ap.add_argument("--post-type", choices=["post", "story", "reel"],
                    default="post", help="Post kind (default: post)")
    ap.add_argument("--schedule-date",
                    help="Explicit ISO datetime (with tz). Overrides auto-slot.")
    ap.add_argument("--no-schedule", action="store_true",
                    help="Do not assign a slot (let GHL default the date)")
    ap.add_argument("--weekdays",
                    help="Cadence days for the auto-slot, e.g. 'mon,wed,fri' (default)")
    ap.add_argument("--time", dest="time_str",
                    help="Slot time HH:MM for the auto-slot (default 10:00)")
    ap.add_argument("--extra-occupied-date", action="append", default=[],
                    dest="extra_occupied",
                    help="YYYY-MM-DD day to treat as occupied (repeatable; for "
                         "distributing several videos in one run)")
    ap.add_argument("--media-type", default="video/mp4",
                    help="Media MIME type (default: video/mp4)")
    ap.add_argument("--user-id",
                    help="Authoring GHL user id (required by API). "
                         "If omitted, taken from GHL_USER_ID or auto-discovered "
                         "from existing posts.")
    ap.add_argument("--media-name",
                    help="Filename shown in the GHL media library "
                         "(default: SharePoint folder name + .mp4)")
    ap.add_argument("--force", action="store_true",
                    help="Publish even to accounts this video already went to "
                         "(overrides the dedup ledger)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Upload nothing; print what would be sent")
    args = ap.parse_args()

    video_path = Path(args.video).expanduser()
    if not video_path.exists():
        sys.exit(f"video not found: {video_path}")

    if args.caption:
        raw_caption = args.caption.strip()
    elif args.caption_file:
        raw_caption = Path(args.caption_file).expanduser().read_text(encoding="utf-8")
    else:
        sys.exit("provide --caption or --caption-file")

    if not args.account_ids:
        sys.exit("provide at least one --account-id (run ghl_discover.py to list them)")

    # --- Dedup: identify the video by content hash, not filename ---
    folder = video_path.parent.name
    media_name = args.media_name or f"{folder}.mp4"
    print("hashing video for dedup …")
    sha = sha256_file(video_path)
    ledger = load_ledger()
    already = published_accounts_for(ledger, sha)
    if already and not args.force:
        target_account_ids = [a for a in args.account_ids if a not in already]
    else:
        target_account_ids = list(args.account_ids)
    skipped = [a for a in args.account_ids if a not in target_account_ids]
    if skipped:
        print(f"  ⏭  already published to {len(skipped)} target account(s) — skipping "
              f"(use --force to override):")
        for e in entries_for(ledger, sha):
            for a in (e.get("account_ids") or []):
                if a in skipped:
                    print(f"       {a}  @ {e.get('published_at')}  post={e.get('post_id')}")
    if not target_account_ids:
        sys.exit("nothing to do — this video was already published to all requested "
                 "accounts. Use --force to publish again.")

    token = _load_env_key("GHL_PRIVATE_INTEGRATION_TOKEN")
    location_id = _load_env_key("GHL_LOCATION_ID")
    client = GHLClient(token, location_id)

    # Map account -> platform, then resolve a per-account caption.
    platform_map = client.account_platform_map()
    targets = []  # list of {account_id, platform, caption}
    for acc in target_account_ids:
        plat = platform_map.get(acc, "")
        targets.append({
            "account_id": acc,
            "platform": plat or "?",
            "caption": resolve_caption(raw_caption, plat, args.caption_section),
        })

    # Resolve ONE shared slot for the whole group (all channels post at the same
    # time; the slot must be free for every target account).
    weekdays = parse_weekdays(args.weekdays)
    hour, minute = parse_time(args.time_str)
    schedule_date = None
    if args.schedule_date:
        schedule_date = datetime.fromisoformat(args.schedule_date)
    elif not args.no_schedule:
        skip = {datetime.fromisoformat(d).date() for d in args.extra_occupied}
        slots = next_free_slots(client, 1, target_account_ids, weekdays=weekdays,
                                hour=hour, minute=minute, skip_days=skip)
        if not slots:
            sys.exit("could not find a free slot")
        schedule_date = slots[0]
    elif args.status == "scheduled":
        sys.exit("--status scheduled needs a date (drop --no-schedule or pass --schedule-date)")

    slot_label = (f"{WEEKDAY_NAMES[schedule_date.weekday()]} "
                  f"{schedule_date.astimezone(BERLIN):%Y-%m-%d %H:%M %Z}"
                  if schedule_date else "(none — GHL default)")

    print(f"video:     {video_path.name} ({video_path.stat().st_size / 1e6:.1f} MB)")
    print(f"sha256:    {sha[:16]}…")
    print(f"media:     {media_name}")
    print(f"status:    {args.status}")
    print(f"slot:      {slot_label}")
    print(f"posts:     {len(targets)} (one per channel, same media uploaded once)")
    for t in targets:
        first = t["caption"].splitlines()[0][:60] if t["caption"] else ""
        print(f"   - {t['platform']:<10} {len(t['caption'])} chars | {first!r}")

    if args.dry_run:
        print("\n[dry-run] no upload, no post created.")
        return

    # Resolve the required userId: flag > env > auto-discover from existing posts.
    user_id = args.user_id or _load_env_key_optional("GHL_USER_ID")
    if not user_id:
        print("no --user-id / GHL_USER_ID; discovering from existing posts …")
        user_id = client.harvest_user_id()
        if not user_id:
            sys.exit("could not determine a userId. Pass --user-id explicitly "
                     "(find it in the GHL UI under Settings → My Staff).")
        print(f"  using discovered userId: {user_id}")

    print("\nuploading media to GHL media library …")
    try:
        media = client.upload_media(video_path, file_name=media_name)
    except GHLError as e:
        sys.exit(f"media upload failed: {e}")
    if not media.get("url"):
        print("WARNING: upload returned no url. Raw response:")
        print(json.dumps(media.get("raw"), indent=2, ensure_ascii=False)[:800])
        sys.exit("cannot create post without a media url")
    print(f"  uploaded: id={media.get('id')} url={media.get('url')}")

    media_entry = {"url": media["url"], "type": args.media_type}
    if media.get("id"):
        media_entry["id"] = media["id"]
    media_entries = [media_entry]

    schedule_iso = (schedule_date.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    if schedule_date else None)
    results_summary = []
    for t in targets:
        print(f"creating post for {t['platform']} …")
        try:
            resp = client.create_post(
                account_ids=[t["account_id"]],
                summary=t["caption"],
                user_id=user_id,
                media=media_entries,
                status=args.status,
                post_type=args.post_type,
                schedule_date=schedule_date,
            )
        except GHLError as e:
            print(f"  ✗ failed: {e}")
            results_summary.append((t["platform"], "FAILED", None))
            continue
        post_id = None
        if isinstance(resp, dict):
            res = resp.get("results") if isinstance(resp.get("results"), dict) else resp
            if isinstance(res, dict):
                post = res.get("post") if isinstance(res.get("post"), dict) else res
                post_id = post.get("id") or post.get("_id")
        # Record this channel in the dedup ledger immediately (git-tracked).
        append_entry(
            ledger,
            sha=sha,
            folder=folder,
            media_name=media_name,
            source_path=str(video_path),
            size_bytes=video_path.stat().st_size,
            account_ids=[t["account_id"]],
            published_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            post_id=post_id,
            media_id=media.get("id"),
            media_url=media.get("url"),
            status=args.status,
            schedule_date=schedule_iso,
        )
        print(f"  ✓ post_id={post_id}")
        results_summary.append((t["platform"], "ok", post_id))

    ok = [r for r in results_summary if r[1] == "ok"]
    print(f"\ndone. {len(ok)}/{len(targets)} post(s) created as {args.status} at {slot_label}.")
    print(f"ledger updated: {LEDGER_PATH.name} (+{len(ok)} entr{'y' if len(ok)==1 else 'ies'})")
    print("Open the GHL Social Planner to review the drafts.")


if __name__ == "__main__":
    main()
