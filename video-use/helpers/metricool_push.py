#!/usr/bin/env python3
"""
Headless Metricool push — the scriptable equivalent of the Metricool MCP
orchestration (prompts/metricool_push_orchestration.md), so the lights-out
watcher can stage posts with NO Claude Code / MCP in the loop.

It talks to the same Metricool REST API the MCP wraps:
    POST {BASE}/v2/scheduler/posts?blogId=<id>&userId=<uid>&integrationSource=MCP
    header  X-Mc-Auth: <METRICOOL_USER_TOKEN>
(endpoint + auth verified against the mcp-metricool source.)

DRAFT-FIRST BY DEFAULT. `--draft` (the default) sets `draft:true` so posts land
as **drafts** in Metricool — never live in a social feed. `--live` is required to
actually schedule for publishing, and even then per CLAUDE.md the first push of a
batch should be a draft the user approves.

Per video × enabled platform with a caption + scheduled_at that isn't pushed yet:
  - build the post `info` (text + hashtags, providers, publicationDate, media=[r2_url])
  - POST it
  - record metricool_post_id / status / pushed_via='metricool' into the manifest

Idempotent: a platform already `status=="pushed"` (or with a metricool_post_id) is
skipped. Manifest is saved after every push.

Usage:
    python metricool_push.py --batch <name>                 # draft push, enabled platforms
    python metricool_push.py --batch <name> --seq 02        # one video
    python metricool_push.py --batch <name> --dry-run       # print plan, no calls
    python metricool_push.py --batch <name> --live          # actually schedule (NOT draft)

Requires in ./.env: METRICOOL_USER_TOKEN, METRICOOL_USER_ID, METRICOOL_BLOG_ID
(VIDEOMAKER_* not needed — media is the public r2_url already in the manifest).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / ".env"
BASE_URL = "https://app.metricool.com/api"
DEFAULT_TZ = "Europe/Zurich"   # default audience timezone (override per brand)
PLATFORMS = ["linkedin", "instagram", "tiktok", "youtube"]


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _http(method: str, url: str, token: str, payload: dict | None = None, timeout: int = 40) -> tuple[int, dict | str]:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"X-Mc-Auth": token, "accept": "application/json"}
    if body is not None:
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode() if hasattr(e, "read") else str(e)
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def fetch_brand(token: str, user_id: str, blog_id: str) -> dict | None:
    """Read-only: confirm the token works and grab the brand timezone."""
    url = f"{BASE_URL}/v2/settings/brands?userId={user_id}&integrationSource=MCP"
    status, data = _http("GET", url, token)
    if status != 200 or not isinstance(data, dict):
        return None
    for item in data.get("data", []):
        if str(item.get("id")) == str(blog_id):
            return {"label": item.get("label"), "id": item.get("id"), "timezone": item.get("timezone")}
    return None


def build_info(*, platform: str, caption: str, hashtags: list[str], media_url: str,
               scheduled_at: str, tz: str, draft: bool, title: str | None) -> dict:
    text = caption.rstrip()
    if hashtags:
        tags = " ".join(h if h.startswith("#") else f"#{h}" for h in hashtags)
        if hashtags[0].lstrip("#").lower() not in text.lower():
            text = f"{text}\n\n{tags}"
    # scheduled_at is ISO w/ offset (e.g. 2026-06-09T12:00:00+02:00); Metricool
    # wants a NAIVE local dateTime + an explicit timezone name.
    naive = scheduled_at.split("+")[0].split("Z")[0]
    if "." in naive:
        naive = naive.split(".")[0]
    info: dict = {
        "autoPublish": True,
        "draft": draft,
        "descendants": [],
        "firstCommentText": "",
        "hasNotReadNotes": False,
        "media": [media_url] if media_url else [],
        "mediaAltText": [],
        "providers": [{"network": platform}],
        "publicationDate": {"dateTime": naive, "timezone": tz},
        "shortener": False,
        "text": text,
    }
    if platform == "youtube":
        info["title"] = title or (text[:90] if text else "Video")
        info["mediaCustomData"] = {"youTube": {"madeForKids": False, "title": info["title"], "type": "short"}}
    return info


def push_one(*, token: str, user_id: str, blog_id: str, platform: str, info: dict, scheduled_at: str) -> tuple[bool, dict | str]:
    naive = scheduled_at.split("+")[0].split("Z")[0].split(".")[0]
    url = (f"{BASE_URL}/v2/scheduler/posts?blogId={blog_id}&userId={user_id}"
           f"&integrationSource=MCP&date={naive}")
    status, data = _http("POST", url, token, payload=info)
    ok = status in (200, 201) and not (isinstance(data, dict) and data.get("error"))
    return ok, data


def main() -> None:
    ap = argparse.ArgumentParser(description="Headless Metricool push (draft-first).")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--seq", nargs="*", help="Only these seqs")
    ap.add_argument("--platform", nargs="*", default=None, help=f"Subset of {PLATFORMS} (default: all enabled)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--draft", action="store_true", default=True, help="Push as DRAFT (default, safe)")
    g.add_argument("--live", dest="draft", action="store_false", help="Schedule for real publishing (NOT draft)")
    ap.add_argument("--blog-id", dest="blog_id", default=None, help="Override Metricool blog_id (else manifest brand, then .env)")
    ap.add_argument("--timezone", default=None, help=f"Override tz (default: from brand, else {DEFAULT_TZ})")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sleep", type=float, default=1.5, help="Seconds between calls (rate-limit guard)")
    args = ap.parse_args()

    env = _load_env()
    token = env.get("METRICOOL_USER_TOKEN")
    user_id = env.get("METRICOOL_USER_ID")
    if not (token and user_id):
        print("ERROR: METRICOOL_USER_TOKEN / METRICOOL_USER_ID must be in .env", file=sys.stderr)
        sys.exit(2)

    manifest_path = REPO_ROOT / "batches" / args.batch / "manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: no manifest at {manifest_path}", file=sys.stderr)
        sys.exit(2)
    manifest = json.loads(manifest_path.read_text())

    # Blog (= Metricool brand) is PER CLIENT: prefer the batch manifest's brand
    # blog_id (set by batch_init from the brand's metricool.json). The .env
    # METRICOOL_BLOG_ID is ONLY a fallback for the "default" brand — a NAMED brand
    # without its own blog_id must NOT silently fall back, or its reels would post
    # to the default account (cross-account leak). CLI --blog-id always wins.
    batch_brand = manifest.get("brand", "default")
    blog_id = args.blog_id or (manifest.get("metricool") or {}).get("default_blog_id")
    if not blog_id and batch_brand == "default":
        blog_id = env.get("METRICOOL_BLOG_ID")
    if not blog_id:
        print(f"ERROR: no Metricool blog_id. Set it in brand-guidelines/{manifest.get('brand','<brand>')}/"
              f"metricool.json (blog_id), or manifest.metricool.default_blog_id, or .env METRICOOL_BLOG_ID, "
              f"or pass --blog-id.", file=sys.stderr)
        sys.exit(2)

    # Verify token + timezone (read-only). Non-fatal on failure (use default tz).
    brand = fetch_brand(token, user_id, blog_id) if not args.dry_run else None
    tz = args.timezone or (brand or {}).get("timezone") or DEFAULT_TZ
    mode = "DRAFT" if args.draft else "LIVE (publishing!)"
    print(f"Metricool push — batch '{args.batch}' · blog {blog_id} · tz {tz} · mode {mode}")
    if brand:
        print(f"  brand verified: {brand.get('label')} (id {brand.get('id')})")
    elif not args.dry_run:
        print("  ! could not verify brand via API — continuing with default tz. Check token if pushes fail.")

    seq_filter = set(args.seq) if args.seq else None
    plat_filter = set(args.platform) if args.platform else None

    pushed = skipped = failed = 0
    for v in manifest.get("videos", []):
        if seq_filter and v["seq"] not in seq_filter:
            continue
        media_url = v.get("r2_url")
        for platform in PLATFORMS:
            if plat_filter and platform not in plat_filter:
                continue
            post = v.get("posts", {}).get(platform)
            if not post or not post.get("enabled"):
                continue
            if post.get("status") == "pushed" or post.get("metricool_post_id"):
                print(f"  [{v['seq']}/{platform}] already pushed — skip")
                skipped += 1
                continue
            caption = (post.get("caption") or "").strip()
            scheduled_at = post.get("scheduled_at")
            if not caption or not scheduled_at:
                print(f"  [{v['seq']}/{platform}] missing caption or scheduled_at — skip")
                skipped += 1
                continue
            if platform in ("instagram", "tiktok", "youtube") and not media_url:
                print(f"  [{v['seq']}/{platform}] needs media but no r2_url — skip")
                skipped += 1
                continue

            info = build_info(platform=platform, caption=caption, hashtags=post.get("hashtags") or [],
                              media_url=media_url, scheduled_at=scheduled_at, tz=tz,
                              draft=args.draft, title=post.get("title"))

            if args.dry_run:
                print(f"  [{v['seq']}/{platform}] DRY-RUN → {mode} @ {scheduled_at}  ({len(info['text'])} chars, media={'yes' if media_url else 'no'})")
                pushed += 1
                continue

            ok, resp = push_one(token=token, user_id=user_id, blog_id=blog_id,
                                platform=platform, info=info, scheduled_at=scheduled_at)
            resp_trim = (json.dumps(resp)[:500] if isinstance(resp, (dict, list)) else str(resp)[:500])
            if ok:
                post_id = resp.get("data", {}).get("id") if isinstance(resp, dict) else None
                post["metricool_post_id"] = post_id
                post["metricool_response"] = resp_trim
                post["pushed_via"] = "metricool"
                post["status"] = "pushed"
                pushed += 1
                print(f"  [{v['seq']}/{platform}] ✓ {mode} pushed (id {post_id})")
            else:
                post["status"] = "failed"
                post["metricool_response"] = resp_trim
                failed += 1
                print(f"  [{v['seq']}/{platform}] ✗ FAILED: {resp_trim[:200]}")
            # Persist after every call so a crash never loses progress.
            manifest["updated_at"] = now_iso()
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
            time.sleep(args.sleep)

        # Roll up per-video posted stage.
        enabled = [p for p in PLATFORMS if v.get("posts", {}).get(p, {}).get("enabled")]
        if enabled and all(v["posts"][p].get("status") == "pushed" for p in enabled):
            v.setdefault("stages", {})["posted"] = {"at": now_iso(),
                "platform_summary": {p: v["posts"][p].get("status") for p in enabled}}
            if v.get("status") in ("scheduled", "captioned", "rendered"):
                v["status"] = "posted"

    manifest["updated_at"] = now_iso()
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"\ndone. pushed={pushed} skipped={skipped} failed={failed}  "
          f"({'DRAFT — verify in Metricool, nothing is live' if args.draft else 'LIVE'})")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
