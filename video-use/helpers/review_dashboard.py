"""Generate a static HTML review dashboard for a batch.

Reads the batch manifest and emits `batches/<batch>/review.html` containing
one card per video with: thumbnail, cut reasoning, all 4 platform captions,
proposed schedule times. Bottom has a textarea for shorthand corrections.

User opens this in browser, scrolls, jots exceptions, then pastes the
shorthand back into the Claude chat to trigger fix loops.

No JS backend — fully static.

Usage:
    python helpers/review_dashboard.py --batch vertrieb-2026-w22
    python helpers/review_dashboard.py --batch <name> --open
"""

from __future__ import annotations

import argparse
import html as _html
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text())


def esc(s: str | None) -> str:
    return _html.escape(s or "")


def render_caption_block(platform: str, post: dict, tz: ZoneInfo) -> str:
    enabled = post.get("enabled", False)
    if not enabled:
        return f'''<div class="caption-block disabled">
  <div class="platform-tag">{platform.upper()} <span class="dim">— disabled (OAuth pending)</span></div>
</div>'''

    caption = post.get("caption")
    if caption is None:
        return f'''<div class="caption-block pending">
  <div class="platform-tag">{platform.upper()} <span class="dim">— caption pending</span></div>
</div>'''

    scheduled = post.get("scheduled_at")
    if scheduled:
        try:
            dt = datetime.fromisoformat(scheduled).astimezone(tz)
            schedule_str = dt.strftime("%a %d %b %H:%M CET")
        except Exception:
            schedule_str = scheduled
    else:
        schedule_str = "unscheduled"

    hashtags = post.get("hashtags", []) or []
    hashtag_line = " ".join(hashtags)
    extra_top = ""
    if platform == "youtube" and post.get("title"):
        extra_top = f'<div class="yt-title"><strong>Title:</strong> {esc(post["title"])}</div>'

    return f'''<div class="caption-block">
  <div class="platform-tag">{platform.upper()} <span class="schedule">{esc(schedule_str)}</span></div>
  {extra_top}
  <pre class="caption">{esc(caption)}</pre>
  <div class="hashtags">{esc(hashtag_line)}</div>
</div>'''


def render_video_card(video: dict, manifest: dict, tz: ZoneInfo) -> str:
    seq = video["seq"]
    slug = video.get("slug", "")
    project_dir = video["project_dir"]
    render_stage = video["stages"].get("rendered") or {}
    duration_s = render_stage.get("duration_s", 0.0)
    thumbnail_rel = render_stage.get("thumbnail") or f"thumbnails/{seq}.jpg"
    # Resolve to relative path from review.html (which lives in batches/<batch>/)
    thumb_path = Path(thumbnail_rel)
    if thumb_path.is_absolute() or "/" in str(thumb_path):
        # Strip batches/<batch>/ prefix if present
        parts = thumb_path.parts
        if "thumbnails" in parts:
            idx = parts.index("thumbnails")
            thumb_rel = "/".join(parts[idx:])
        else:
            thumb_rel = thumb_path.name
    else:
        thumb_rel = str(thumb_path)

    render_path = render_stage.get("render", "")
    # final.mp4 lives in projects/<batch>__<seq>/renders/. From review.html,
    # we need to go up one level (to repo root) and down again.
    if render_path:
        render_href = f"../../{render_path}" if not render_path.startswith("../") else render_path
    else:
        render_href = "#"

    edl_stage = video["stages"].get("edl_planned") or {}
    reasoning = edl_stage.get("reasoning_summary", "(EDL not generated yet)")

    caption_blocks = "\n".join(
        render_caption_block(p, video["posts"][p], tz)
        for p in ("linkedin", "instagram", "tiktok", "youtube")
    )

    status = esc(video.get("status", ""))

    return f'''<div class="card" id="card-{seq}">
  <div class="card-head">
    <div class="seq-badge">{seq}</div>
    <div class="card-title">
      <h3>{esc(slug)}</h3>
      <div class="card-meta">{duration_s:.1f}s · status={status} · <a href="{esc(render_href)}" target="_blank">▶ final.mp4</a></div>
    </div>
  </div>
  <div class="card-body">
    <div class="thumb-col">
      <img src="{esc(thumb_rel)}" alt="thumb {seq}" loading="lazy">
      <div class="reasoning">{esc(reasoning)}</div>
    </div>
    <div class="caption-col">
      {caption_blocks}
    </div>
  </div>
</div>'''


def render_dashboard(manifest: dict, batch_dir: Path) -> str:
    tz = ZoneInfo(manifest["common"].get("audience_timezone", "Europe/Berlin"))
    batch_name = manifest["batch_name"]
    n_videos = len(manifest["videos"])

    # Count scheduled posts
    n_posts = sum(
        1 for v in manifest["videos"]
        for p, post in v["posts"].items()
        if post.get("enabled") and post.get("scheduled_at")
    )

    # Compute schedule window
    all_times = []
    for v in manifest["videos"]:
        for p, post in v["posts"].items():
            if post.get("scheduled_at"):
                try:
                    all_times.append(datetime.fromisoformat(post["scheduled_at"]).astimezone(tz))
                except Exception:
                    pass
    if all_times:
        all_times.sort()
        window_str = f"{all_times[0].strftime('%d %b')} – {all_times[-1].strftime('%d %b %Y')}"
        days = (all_times[-1].date() - all_times[0].date()).days + 1
        avg_per_day = len(all_times) / max(days, 1)
    else:
        window_str = "no slots assigned"
        avg_per_day = 0.0

    cards = "\n".join(render_video_card(v, manifest, tz) for v in manifest["videos"])

    return f'''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Review — {esc(batch_name)}</title>
<style>
  :root {{
    --bg: #fafaf9;
    --ink-950: #070910;
    --ink-700: #44464a;
    --ink-500: #8c8d92;
    --ink-200: #e0e1e4;
    --ink-100: #ededee;
    --brand-500: #DBAA67;
    --brand-50: #fbf5ec;
    --danger: #dc2626;
    --warn: #d97706;
  }}
  html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--ink-950);
                font-family: Inter, system-ui, sans-serif; }}
  header {{ position: sticky; top: 0; background: var(--ink-950); color: #fff;
            padding: 18px 32px; box-shadow: 0 2px 12px rgba(0,0,0,0.18); z-index: 10; }}
  header h1 {{ margin: 0; font-size: 22px; font-weight: 700; letter-spacing: -0.01em; }}
  header .sub {{ font-size: 14px; color: #c8c9cc; margin-top: 4px; }}
  main {{ max-width: 1180px; margin: 24px auto 80px; padding: 0 24px; }}
  .card {{ background: #fff; border: 1px solid var(--ink-100); border-radius: 16px;
           margin-bottom: 28px; overflow: hidden;
           box-shadow: 0 2px 10px rgba(7,9,16,0.04); }}
  .card-head {{ display: flex; gap: 16px; align-items: center; padding: 18px 22px;
                background: var(--brand-50); border-bottom: 1px solid var(--ink-100); }}
  .seq-badge {{ background: var(--ink-950); color: var(--brand-500);
                width: 48px; height: 48px; border-radius: 12px;
                display: flex; align-items: center; justify-content: center;
                font-weight: 800; font-size: 22px; font-family: "Bricolage Grotesque", Inter, sans-serif; }}
  .card-title h3 {{ margin: 0; font-size: 18px; font-weight: 700; }}
  .card-meta {{ font-size: 13px; color: var(--ink-500); margin-top: 4px; }}
  .card-meta a {{ color: var(--brand-500); text-decoration: none; font-weight: 600; }}
  .card-body {{ display: grid; grid-template-columns: 220px 1fr; gap: 20px; padding: 22px; }}
  .thumb-col img {{ width: 100%; border-radius: 10px; display: block;
                    border: 1px solid var(--ink-200); }}
  .reasoning {{ margin-top: 12px; font-size: 13px; color: var(--ink-700); line-height: 1.45; }}
  .caption-col {{ display: flex; flex-direction: column; gap: 12px; }}
  .caption-block {{ padding: 14px 16px; background: var(--ink-100); border-radius: 10px;
                    border-left: 3px solid var(--brand-500); }}
  .caption-block.disabled {{ background: #f5f5f4; border-left-color: var(--ink-200);
                              color: var(--ink-500); }}
  .caption-block.pending {{ background: #fef3c7; border-left-color: var(--warn); }}
  .platform-tag {{ font-weight: 700; font-size: 12px; letter-spacing: 0.08em;
                   text-transform: uppercase; color: var(--ink-950); margin-bottom: 8px;
                   display: flex; justify-content: space-between; align-items: baseline; }}
  .platform-tag .schedule {{ color: var(--ink-700); font-weight: 600; }}
  .platform-tag .dim {{ color: var(--ink-500); font-weight: 400; }}
  .yt-title {{ font-size: 14px; color: var(--ink-700); margin-bottom: 8px; }}
  .caption {{ margin: 0; padding: 0; background: transparent; border: 0;
              font-family: inherit; font-size: 14px; line-height: 1.5;
              white-space: pre-wrap; color: var(--ink-950); }}
  .hashtags {{ font-size: 12px; color: var(--brand-500); margin-top: 8px; font-weight: 600; }}
  .summary {{ background: #fff; border: 1px solid var(--ink-100); border-radius: 12px;
              padding: 18px 22px; margin-bottom: 28px;
              display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }}
  .summary .stat .num {{ font-size: 26px; font-weight: 800; color: var(--ink-950); }}
  .summary .stat .lbl {{ font-size: 12px; color: var(--ink-500);
                          text-transform: uppercase; letter-spacing: 0.06em; }}
  .corrections {{ background: #fff; border: 1px solid var(--ink-100); border-radius: 12px;
                  padding: 20px; margin-top: 36px; }}
  .corrections h2 {{ margin: 0 0 12px; font-size: 16px; }}
  .corrections .hint {{ font-size: 13px; color: var(--ink-500); margin-bottom: 10px; }}
  textarea {{ width: 100%; min-height: 140px; box-sizing: border-box;
              font-family: ui-monospace, "SF Mono", Menlo, monospace;
              font-size: 13px; padding: 12px; border: 1px solid var(--ink-200);
              border-radius: 8px; resize: vertical; }}
</style>
</head>
<body>
<header>
  <h1>Review — {esc(batch_name)}</h1>
  <div class="sub">Brand: {esc(manifest.get('brand','default'))} · Generated {esc(manifest.get('updated_at',''))}</div>
</header>
<main>
  <div class="summary">
    <div class="stat"><div class="num">{n_videos}</div><div class="lbl">Videos</div></div>
    <div class="stat"><div class="num">{n_posts}</div><div class="lbl">Scheduled Posts</div></div>
    <div class="stat"><div class="num">{esc(window_str)}</div><div class="lbl">Window</div></div>
    <div class="stat"><div class="num">{avg_per_day:.1f}/d</div><div class="lbl">Avg Posts/Day</div></div>
  </div>

  {cards}

  <div class="corrections">
    <h2>Korrekturen (Shorthand-Notation)</h2>
    <div class="hint">
      Tippe Exceptions hier ein, dann paste den Inhalt zurück in den Chat mit Claude.
      Beispiele:
      <code>03: re-cut shorter</code> ·
      <code>07: linkedin 2026-05-28 09:15</code> ·
      <code>12: skip tiktok</code>
    </div>
    <textarea placeholder="03: re-cut shorter (drop intro)&#10;07: linkedin 2026-05-28 09:15&#10;12: skip tiktok"></textarea>
  </div>
</main>
</body>
</html>'''


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate review.html for a batch")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--open", action="store_true", help="Open the dashboard in browser after generating")
    args = ap.parse_args()

    batch_dir = REPO_ROOT / "batches" / args.batch
    manifest_path = batch_dir / "manifest.json"
    if not manifest_path.exists():
        sys.exit(f"manifest not found: {manifest_path}")

    manifest = load_manifest(manifest_path)
    html = render_dashboard(manifest, batch_dir)
    out_path = batch_dir / "review.html"
    out_path.write_text(html)

    print(f"dashboard: {out_path}")
    print(f"  videos: {len(manifest['videos'])}")
    if args.open:
        subprocess.Popen(["open", str(out_path)])


if __name__ == "__main__":
    main()
