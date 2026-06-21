"""Push all approved posts from a batch manifest to Postiz.

Reads the batch manifest. For each video where:
- status >= scheduled AND
- per-platform post.enabled=true AND
- per-platform post.status in {pending, scheduled, failed}

…uploads the rendered video once and creates one Postiz post per platform.
Updates the manifest after each call (idempotent on re-run).

Rate-limited internally (default 90/hr, Postiz self-hosted limit).
Retries failed pushes 3× with exponential backoff.

Use `--draft-mode` to post as drafts (sandbox) — recommended for first run!

Usage:
    python helpers/postiz_push.py --batch vertrieb-2026-w22 --draft-mode  # safe first run
    python helpers/postiz_push.py --batch vertrieb-2026-w22                # live push
    python helpers/postiz_push.py --batch <name> --only-seq 03,07         # subset
    python helpers/postiz_push.py --batch <name> --only-platform linkedin # one platform
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transcribe import _load_env_key  # noqa: E402
from postiz_client import PostizClient, post_video_to_postiz, PostizError  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text())


def save_manifest(path: Path, manifest: dict) -> None:
    manifest["updated_at"] = now_iso()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    os.replace(tmp, path)


def resolve_integration_id(manifest: dict, platform: str) -> str | None:
    """Look up integration_id from manifest, expanding ${ENV_VAR} references."""
    raw = manifest["postiz"]["integration_ids"].get(platform)
    if not raw:
        return None
    if raw.startswith("${") and raw.endswith("}"):
        env_var = raw[2:-1]
        value = os.environ.get(env_var, "").strip()
        if not value:
            # Try loading from .env via _load_env_key
            try:
                value = _load_env_key(env_var)
            except SystemExit:
                return None
        return value or None
    return raw


def build_log_entry(seq: str, results: dict) -> str:
    parts = [f"[{now_iso()}] seq={seq}"]
    for platform, r in results.items():
        status = r.get("status", "?")
        if status == "pushed":
            parts.append(f"{platform}=ok({r.get('post_id', 'no-id')})")
        else:
            parts.append(f"{platform}=FAIL({r.get('error', 'unknown')[:80]})")
    return " ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Push scheduled posts from a batch to Postiz")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--draft-mode", action="store_true",
                    help="Post as drafts (sandbox). Recommended for first run.")
    ap.add_argument("--only-seq", default=None, help="Comma-separated sequence numbers")
    ap.add_argument("--only-platform", default=None,
                    help="Only push this platform (linkedin|instagram|tiktok|youtube)")
    ap.add_argument("--rate-limit-per-hour", type=int, default=None,
                    help="Override manifest's postiz.rate_limit_per_hour")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be pushed, don't call API")
    args = ap.parse_args()

    batch_dir = REPO_ROOT / "batches" / args.batch
    manifest_path = batch_dir / "manifest.json"
    if not manifest_path.exists():
        sys.exit(f"manifest not found: {manifest_path}")

    manifest = load_manifest(manifest_path)
    api_url = manifest["postiz"]["api_url"]
    api_key = _load_env_key("POSTIZ_API_KEY")

    # Rate limit → sleep between calls
    rate_limit = args.rate_limit_per_hour or manifest["postiz"].get("rate_limit_per_hour", 90)
    sleep_between = max(0.0, 3600.0 / max(rate_limit, 1))

    only_seqs = set(s.strip() for s in args.only_seq.split(",")) if args.only_seq else None
    only_platform = args.only_platform.lower() if args.only_platform else None

    log_dir = batch_dir / "postiz"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "push.log"
    responses_dir = log_dir / "responses"
    responses_dir.mkdir(exist_ok=True)

    client = PostizClient(api_url, api_key)
    print(f"target: {api_url}")
    print(f"draft-mode: {args.draft_mode}")
    print(f"rate-limit: {rate_limit}/hr (sleep {sleep_between:.1f}s between calls)")

    pushed = 0
    failed = 0
    skipped = 0
    for v in manifest["videos"]:
        if only_seqs and v["seq"] not in only_seqs:
            continue
        if not v["stages"].get("rendered"):
            continue
        render_path = REPO_ROOT / v["stages"]["rendered"]["render"]
        if not render_path.exists():
            print(f"  ! seq {v['seq']}: render file missing ({render_path})")
            continue

        posts_to_publish: list[dict] = []
        platforms_skipped_for_this_video: list[str] = []
        for platform in ("linkedin", "instagram", "tiktok", "youtube"):
            if only_platform and platform != only_platform:
                continue
            post = v["posts"].get(platform)
            if not post:
                continue
            if not post.get("enabled"):
                platforms_skipped_for_this_video.append(f"{platform}=disabled")
                continue
            if post.get("status") == "pushed":
                platforms_skipped_for_this_video.append(f"{platform}=already-pushed")
                continue
            if not post.get("caption"):
                platforms_skipped_for_this_video.append(f"{platform}=no-caption")
                continue
            integration_id = resolve_integration_id(manifest, platform)
            if not integration_id:
                platforms_skipped_for_this_video.append(f"{platform}=no-integration-id")
                continue
            sched = post.get("scheduled_at")
            sched_dt = None
            if sched and not args.draft_mode:
                sched_dt = datetime.fromisoformat(sched)
            posts_to_publish.append({
                "platform": platform,
                "integration_id": integration_id,
                "content": post["caption"],
                "scheduled_at": sched_dt,
            })

        if not posts_to_publish:
            skipped += 1
            if platforms_skipped_for_this_video:
                print(f"  - seq {v['seq']}: skipped ({', '.join(platforms_skipped_for_this_video)})")
            continue

        platforms = [p["platform"] for p in posts_to_publish]
        print(f"  > seq {v['seq']}: pushing {platforms}", flush=True)

        if args.dry_run:
            for pr in posts_to_publish:
                print(f"      DRY-RUN {pr['platform']}: caption={pr['content'][:80]}...")
            continue

        try:
            results = post_video_to_postiz(
                client=client,
                video_path=render_path,
                posts_to_publish=posts_to_publish,
                draft=args.draft_mode,
            )
        except Exception as e:
            results = {p["platform"]: {"status": "failed", "error": str(e)} for p in posts_to_publish}

        # Update manifest per-platform
        for platform, r in results.items():
            post = v["posts"][platform]
            if r["status"] == "pushed":
                post["status"] = "pushed"
                post["postiz_post_id"] = r.get("post_id")
                post["postiz_response"] = r.get("response")
                pushed += 1
                # Per-platform response log
                (responses_dir / f"{v['seq']}-{platform}.json").write_text(
                    json.dumps(r, indent=2, ensure_ascii=False, default=str)
                )
            else:
                post["status"] = "failed"
                post["postiz_response"] = {"error": r.get("error")}
                failed += 1

        v["stages"]["posted"] = {"at": now_iso()}
        save_manifest(manifest_path, manifest)

        # Append to log
        with open(log_path, "a") as f:
            f.write(build_log_entry(v["seq"], results) + "\n")

        if sleep_between > 0:
            time.sleep(sleep_between)

    print(f"\ndone — pushed {pushed}, failed {failed}, videos skipped {skipped}")
    if failed:
        print(f"see {log_path} for details. re-run to retry failed posts.")
        sys.exit(1)


if __name__ == "__main__":
    main()
