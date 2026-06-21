"""Generate per-platform social captions for every video in a batch.

For each video in the batch manifest with status >= rendered, calls the
Anthropic API ONCE per video, producing all 4 platform captions (LinkedIn,
Instagram, TikTok, YouTube) in a single response. Writes captions back to
the manifest under videos[i].posts[platform].

Uses claude-sonnet-4-6 by default (fast, good enough for captions; opus
overkill). Override with --model.

Rate-limits to avoid burst-hitting Anthropic API; ~30 videos = ~30 API calls.

Usage:
    python helpers/caption_gen.py --batch vertrieb-2026-w22
    python helpers/caption_gen.py --batch <name> --model claude-opus-4-7
    python helpers/caption_gen.py --batch <name> --only-seq 03,07
    python helpers/caption_gen.py --batch <name> --force  # regenerate even if captioned
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transcribe import _load_env_key  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "caption_subagent.md"
DEFAULT_MODEL = "claude-sonnet-4-6"


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


def read_brand_context(brand_path: Path) -> str:
    """Concatenate brand SKILL.md + README.md + optional tone.md."""
    parts: list[str] = []
    for fname in ("SKILL.md", "README.md", "tone.md"):
        p = brand_path / fname
        if p.exists():
            parts.append(f"# === {fname} ===\n\n{p.read_text()}")
    return "\n\n".join(parts)


def read_platform_templates(brand_path: Path) -> dict[str, str]:
    """Return {platform: template_md} for all 4 platforms."""
    templates_dir = brand_path / "caption-templates"
    out: dict[str, str] = {}
    for platform in ("linkedin", "instagram", "tiktok", "youtube"):
        p = templates_dir / f"{platform}.md"
        if not p.exists():
            sys.exit(f"missing template: {p}")
        out[platform] = p.read_text()
    return out


def read_transcript_text(transcript_path: Path) -> str:
    """Return just the .text field from the normalized transcript JSON."""
    data = json.loads(transcript_path.read_text())
    return data.get("text", "")


def build_prompt(
    *,
    prompt_md: str,
    brand_name: str,
    brand_context: str,
    platform_templates: dict[str, str],
    transcript_text: str,
    edl_reasoning: str,
    audience_profile: str,
    audience_timezone: str,
    render_duration_s: float,
    batch_name: str,
    seq: str,
    slug: str,
) -> str:
    templates_block = "\n\n".join(
        f"## === Template: {platform.upper()} ===\n\n{md}"
        for platform, md in platform_templates.items()
    )
    return f"""{prompt_md}

---

## ACTUAL INPUTS FOR THIS VIDEO

- BATCH_NAME: {batch_name}
- SEQ: {seq}
- SLUG: {slug}
- BRAND_NAME: {brand_name}
- AUDIENCE_PROFILE: {audience_profile}
- AUDIENCE_TIMEZONE: {audience_timezone}
- RENDER_DURATION_S: {render_duration_s}

## BRAND CONTEXT (read first, this is your voice ground-truth)

{brand_context}

## PLATFORM TEMPLATES (follow strictly per platform)

{templates_block}

## TRANSCRIPT TEXT (only source of facts/claims)

{transcript_text}

## EDL REASONING SUMMARY (what the editor kept, what the message is)

{edl_reasoning}

---

## OUTPUT

Return EXACTLY the JSON object specified in the prompt above. No markdown
code fence, no commentary before or after. Just the raw JSON starting with
{{ and ending with }}.
"""


def extract_json(text: str) -> dict:
    """Tolerantly extract JSON from a model response.

    Handles three cases:
    1. Pure JSON (ideal)
    2. JSON wrapped in ```json ... ``` code fence
    3. JSON with surrounding commentary (extract the {...} block)
    """
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        return json.loads(fence_match.group(1))
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return json.loads(brace_match.group(0))
    raise ValueError(f"no JSON object found in response:\n{text[:500]}")


def call_anthropic(prompt: str, model: str, api_key: str, max_tokens: int = 4000) -> str:
    """Single message call to Anthropic. Returns plain text content."""
    import anthropic  # imported lazily so help text works without the dep

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    # content is a list of blocks; we want the text from the first text block
    parts = [b.text for b in resp.content if hasattr(b, "text")]
    return "\n".join(parts).strip()


def generate_for_video(
    *,
    video: dict,
    manifest: dict,
    brand_context: str,
    platform_templates: dict[str, str],
    prompt_md: str,
    api_key: str,
    model: str,
) -> dict:
    """Returns {platform: {caption, hashtags, title?}} dict."""
    project_dir = REPO_ROOT / video["project_dir"]
    raw_path = REPO_ROOT / video["raw_path"]
    transcript_rel = video["stages"]["transcribed"].get("transcript")
    if not transcript_rel:
        raise RuntimeError(f"video {video['seq']} has no transcript")
    transcript_path = REPO_ROOT / transcript_rel
    transcript_text = read_transcript_text(transcript_path)

    edl_stage = video["stages"].get("edl_planned") or {}
    edl_reasoning = edl_stage.get("reasoning_summary", "(no EDL reasoning available)")

    render_stage = video["stages"].get("rendered") or {}
    duration_s = render_stage.get("duration_s", 0.0)

    brand_name = manifest.get("brand", "default")

    prompt = build_prompt(
        prompt_md=prompt_md,
        brand_name=brand_name,
        brand_context=brand_context,
        platform_templates=platform_templates,
        transcript_text=transcript_text,
        edl_reasoning=edl_reasoning,
        audience_profile=manifest["common"]["audience_profile"],
        audience_timezone=manifest["common"]["audience_timezone"],
        render_duration_s=duration_s,
        batch_name=manifest["batch_name"],
        seq=video["seq"],
        slug=video.get("slug", ""),
    )

    text = call_anthropic(prompt, model=model, api_key=api_key)
    return extract_json(text)


def apply_to_manifest(video: dict, captions: dict) -> None:
    """Write generated captions into manifest.videos[i].posts[platform]."""
    for platform in ("linkedin", "instagram", "tiktok", "youtube"):
        rec = captions.get(platform)
        if not rec:
            continue
        post = video["posts"].get(platform)
        if not post:
            continue
        post["caption"] = rec.get("caption")
        post["hashtags"] = rec.get("hashtags", [])
        if platform == "youtube":
            post["title"] = rec.get("title")
    video["stages"]["captioned"] = {"at": now_iso()}
    if video.get("status") in ("rendered", "captioned"):
        video["status"] = "captioned"


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate per-platform captions for every video in a batch")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--only-seq", default=None,
                    help="Comma-separated sequence numbers to process (e.g. 03,07)")
    ap.add_argument("--force", action="store_true",
                    help="Regenerate captions even if already present")
    ap.add_argument("--rate-limit-ms", type=int, default=500,
                    help="Sleep between API calls (default 500ms)")
    args = ap.parse_args()

    manifest_path = REPO_ROOT / "batches" / args.batch / "manifest.json"
    manifest = load_manifest(manifest_path)

    brand_path = REPO_ROOT / manifest["brand_path"]
    brand_context = read_brand_context(brand_path)
    platform_templates = read_platform_templates(brand_path)
    prompt_md = PROMPT_PATH.read_text()

    only_seqs = set(s.strip() for s in args.only_seq.split(",")) if args.only_seq else None
    api_key = _load_env_key("ANTHROPIC_API_KEY")

    todo = []
    for v in manifest["videos"]:
        if only_seqs and v["seq"] not in only_seqs:
            continue
        if not args.force and v["stages"].get("captioned"):
            continue
        # Need a rendered video before we can caption it (need duration + EDL reasoning)
        if not v["stages"].get("rendered"):
            continue
        todo.append(v)

    if not todo:
        print("nothing to caption (use --force to regenerate)")
        return

    print(f"generating captions for {len(todo)} videos with model={args.model}")
    errors = 0
    for i, v in enumerate(todo, start=1):
        try:
            print(f"  [{i}/{len(todo)}] seq={v['seq']} ({v.get('slug','')})", flush=True)
            captions = generate_for_video(
                video=v,
                manifest=manifest,
                brand_context=brand_context,
                platform_templates=platform_templates,
                prompt_md=prompt_md,
                api_key=api_key,
                model=args.model,
            )
            apply_to_manifest(v, captions)
            save_manifest(manifest_path, manifest)
            print(f"    + 4 captions written ({sum(len(c.get('caption','')) for c in captions.values())} chars total)")
        except Exception as e:
            errors += 1
            print(f"    x FAILED: {e}")

        if i < len(todo) and args.rate_limit_ms > 0:
            time.sleep(args.rate_limit_ms / 1000.0)

    print(f"\ndone. {len(todo) - errors} succeeded, {errors} failed")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
