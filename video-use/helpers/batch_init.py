"""Initialize a batch: scaffold manifest + per-video projects + transcribe all.

Reads raw videos from `raw/batches/<batch>/`, creates a manifest, scaffolds
per-video project directories matching the existing convention, then runs
Whisper transcription (parallel) and packs phrase-level transcripts.

This is the entry point for Phase 1-2 of the batch workflow. After this
runs, the manifest is at `batches/<batch>/manifest.json` with status
`transcribed` per video, and downstream Phase 3 (EDL generation via
sub-agents) can begin.

Idempotent: re-running skips already-transcribed videos and preserves
existing manifest state. Safe to re-run after partial failures.

Usage:
    python helpers/batch_init.py --batch vertrieb-2026-w22
    python helpers/batch_init.py --batch <name> --brand acme --engine whisper
    python helpers/batch_init.py --batch <name> --workers 6 --language de
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make sibling helpers importable when this script is run directly
sys.path.insert(0, str(Path(__file__).resolve().parent))

from transcribe import transcribe_one, load_openai_key, load_elevenlabs_key  # noqa: E402
from transcribe_batch import find_videos  # noqa: E402


VIDEO_EXTS = {".mp4", ".MP4", ".mov", ".MOV", ".mkv", ".MKV", ".avi", ".AVI", ".m4v"}
SCHEMA_VERSION = "1.0"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PLATFORMS = ["linkedin", "instagram", "tiktok", "youtube"]
INITIAL_ENABLED = {"linkedin": True, "instagram": False, "tiktok": False, "youtube": False}

DEFAULT_SLOTS_CET = {
    "linkedin":  ["Tue 07:45", "Wed 07:45", "Thu 07:45", "Tue 12:00"],
    "instagram": ["Tue 08:30", "Wed 08:30", "Thu 08:30", "Tue 18:00"],
    "tiktok":    ["Tue 11:30", "Wed 11:30", "Thu 11:30", "Wed 19:30"],
    "youtube":   ["Tue 17:00", "Thu 17:00", "Sat 10:00"],
}

# Vocab biases for Whisper. Helpful when Whisper mishears domain terms or proper
# nouns. Set your own per brand: list recurring names, product names and technical
# terms here (comma-separated), or override per-batch via --vocab-prompt / by
# editing manifest.common.whisper_prompt.
DEFAULT_WHISPER_PROMPTS = {
    "default": "",
}


# -------- Manifest atomic I/O ------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_manifest(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def save_manifest(path: Path, manifest: dict) -> None:
    manifest["updated_at"] = now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    os.replace(tmp, path)


# -------- Manifest construction ----------------------------------------------


def empty_post_record(enabled: bool) -> dict:
    return {
        "enabled": enabled,
        "caption": None,
        "hashtags": [],
        "scheduled_at": None,
        "scheduled_at_locked": False,
        "metricool_post_id": None,
        "metricool_response": None,
        "postiz_post_id": None,
        "postiz_response": None,
        "pushed_via": None,
        "status": "pending",
    }


def empty_video_record(seq: str, raw_path: Path, project_dir: Path, slug: str,
                       enabled: set[str] | None = None) -> dict:
    def _is_on(p: str) -> bool:
        return (p in enabled) if enabled is not None else INITIAL_ENABLED.get(p, False)
    return {
        "seq": seq,
        "slug": slug,
        "raw_path": str(raw_path.relative_to(REPO_ROOT)),
        "project_dir": str(project_dir.relative_to(REPO_ROOT)),
        "status": "created",
        "stages": {
            "transcribed": None,
            "edl_planned": None,
            "composed": None,
            "rendered": None,
            "captioned": None,
            "scheduled": None,
            "posted": None,
        },
        "posts": {p: empty_post_record(_is_on(p)) for p in DEFAULT_PLATFORMS},
        "user_corrections": [],
    }


def _brand_metricool(brand: str) -> dict:
    """Read brand-guidelines/<brand>/metricool.json (per-client Metricool config).

    Lets each agency client carry their own Metricool brand: drop a small JSON
    in their brand folder and every batch for that brand posts to THEIR account.
    Returns {} if missing/unreadable (then push falls back to .env METRICOOL_BLOG_ID).
    """
    cfg_path = REPO_ROOT / "brand-guidelines" / brand / "metricool.json"
    if not cfg_path.exists():
        return {}
    try:
        return json.loads(cfg_path.read_text())
    except Exception:
        return {}


def build_manifest(
    batch_name: str,
    brand: str,
    raw_dir: Path,
    videos: list[Path],
    engine: str,
    audience_timezone: str,
    audience_profile: str,
    whisper_prompt: str | None = None,
) -> dict:
    brand_path = f"brand-guidelines/{brand}"
    # Which platforms this brand posts to (e.g. Instagram-only for the IG
    # accounts). From brand-guidelines/<brand>/metricool.json "enabled_platforms";
    # falls back to the global INITIAL_ENABLED (LinkedIn) when not set.
    mc_cfg = _brand_metricool(brand)
    enabled = set(mc_cfg.get("enabled_platforms") or []) or None
    videos_records = []
    for i, v in enumerate(videos, start=1):
        seq = f"{i:02d}"
        slug = v.stem.split("-", 1)[1] if "-" in v.stem else v.stem
        project_dir = REPO_ROOT / "projects" / f"{batch_name}__{seq}"
        videos_records.append(empty_video_record(seq, v, project_dir, slug, enabled))

    return {
        "schema_version": SCHEMA_VERSION,
        "batch_name": batch_name,
        "brand": brand,
        "brand_path": brand_path,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "raw_dir": str(raw_dir.relative_to(REPO_ROOT)),
        "common": {
            "target_aspect": "1080x1920",
            "fps": 30,
            "languages": ["de"],
            "platforms": DEFAULT_PLATFORMS,
            "audience_timezone": audience_timezone,
            "audience_profile": audience_profile,
            "transcription_engine": engine,
            "whisper_prompt": whisper_prompt or DEFAULT_WHISPER_PROMPTS.get(brand, DEFAULT_WHISPER_PROMPTS["default"]),
        },
        "videos": videos_records,
        "metricool": {
            "default_blog_id": _brand_metricool(brand).get("blog_id"),
            "rate_limit_per_hour": 100,
            "_comment": "blog_id auto-filled from brand-guidelines/<brand>/metricool.json if present; "
                        "else set it here or rely on .env METRICOOL_BLOG_ID (single-tenant)."
        },
        "postiz": {
            "api_url": os.environ.get("POSTIZ_API_URL", "http://localhost:5000"),
            "integration_ids": {
                "linkedin":  "${POSTIZ_LINKEDIN_INTEGRATION_ID}",
                "instagram": "${POSTIZ_INSTAGRAM_INTEGRATION_ID}",
                "tiktok":    "${POSTIZ_TIKTOK_INTEGRATION_ID}",
                "youtube":   "${POSTIZ_YOUTUBE_INTEGRATION_ID}",
            },
            "rate_limit_per_hour": 90,
            "_comment": "Fallback posting stack. Self-hosted Postiz Docker (postiz/docker-compose.yml)."
        },
        "schedule_strategy": {
            "start_date": None,  # filled by schedule_plan.py
            "window_days": 14,
            "preferred_slots_cet": DEFAULT_SLOTS_CET,
            "max_per_platform_per_day": 4,
            "min_hours_between_same_platform": 4,
        },
    }


def merge_videos(existing: list[dict], discovered: list[Path], batch_name: str) -> list[dict]:
    """Preserve existing per-video records (status, stages, corrections),
    append new ones for newly-discovered raw files. Re-runs are safe."""
    existing_by_path = {v["raw_path"]: v for v in existing}
    merged = []
    for i, v in enumerate(discovered, start=1):
        rel = str(v.relative_to(REPO_ROOT))
        if rel in existing_by_path:
            merged.append(existing_by_path[rel])
        else:
            seq = f"{i:02d}"
            slug = v.stem.split("-", 1)[1] if "-" in v.stem else v.stem
            project_dir = REPO_ROOT / "projects" / f"{batch_name}__{seq}"
            merged.append(empty_video_record(seq, v, project_dir, slug))
    return merged


# -------- Per-video scaffold -------------------------------------------------


PROJECT_SUBDIRS = [
    "assets",
    "clips",
    "transcripts",
    "compositions",
    "compositions/assets",
    "previews",
    "renders",
    "verify",
]


def scaffold_project_dir(project_dir: Path) -> None:
    for sub in PROJECT_SUBDIRS:
        (project_dir / sub).mkdir(parents=True, exist_ok=True)


# -------- Pack transcripts (calls existing helper) ---------------------------


def pack_transcripts(project_dir: Path) -> None:
    """Invoke pack_transcripts.py to produce takes_packed.md for one project."""
    helpers_dir = Path(__file__).resolve().parent
    cmd = [
        sys.executable,
        str(helpers_dir / "pack_transcripts.py"),
        "--edit-dir", str(project_dir),
        "--silence-threshold", "0.4",
    ]
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    subprocess.run(cmd, check=True, env=env, stdout=subprocess.DEVNULL)


# -------- Main orchestration -------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="Initialize a batch + transcribe all videos")
    ap.add_argument("--batch", required=True, help="Batch name (kebab-case)")
    ap.add_argument("--brand", default="default", help="Brand folder under brand-guidelines/")
    ap.add_argument("--raw", type=Path, default=None,
                    help="Raw videos dir (default: raw/batches/<batch>)")
    ap.add_argument("--engine", choices=["whisper", "scribe"], default="whisper",
                    help="Transcription engine (default: whisper)")
    ap.add_argument("--workers", type=int, default=4, help="Parallel transcription workers")
    ap.add_argument("--language", default="de", help="ISO language code (default: de)")
    ap.add_argument("--audience-timezone", default="Europe/Berlin")
    ap.add_argument("--audience-profile", default="DACH B2B sales / leadership")
    ap.add_argument("--skip-transcribe", action="store_true",
                    help="Only scaffold manifest + dirs, skip transcription")
    ap.add_argument("--only-seq", default=None,
                    help="Comma-separated sequence numbers to transcribe (e.g. 03,07). "
                         "Useful for re-runs after corrections.")
    ap.add_argument("--vocab-prompt", default=None,
                    help="Whisper vocab bias for this batch. Overrides manifest's "
                         "common.whisper_prompt. Critical for German domain terms.")
    args = ap.parse_args()

    batch_name = args.batch.strip()
    raw_dir = (args.raw or REPO_ROOT / "raw" / "batches" / batch_name).resolve()
    batch_dir = REPO_ROOT / "batches" / batch_name
    manifest_path = batch_dir / "manifest.json"

    # 1. Discover raw videos
    if not raw_dir.is_dir():
        sys.exit(f"raw directory not found: {raw_dir}\n"
                 f"Create it and drop your videos: mkdir -p {raw_dir}")

    videos = find_videos(raw_dir)
    if not videos:
        sys.exit(f"no videos found in {raw_dir} (expected .mp4/.mov/.mkv/.avi/.m4v)")

    print(f"batch: {batch_name}")
    print(f"raw dir: {raw_dir.relative_to(REPO_ROOT)}")
    print(f"found {len(videos)} videos")

    # 2. Load or create manifest
    existing = load_manifest(manifest_path)
    if existing:
        print(f"loading existing manifest ({len(existing.get('videos', []))} videos already tracked)")
        # Merge: keep existing video records, add any newly-dropped raw files
        existing["videos"] = merge_videos(existing.get("videos", []), videos, batch_name)
        existing["common"]["transcription_engine"] = args.engine
        manifest = existing
    else:
        print("creating new manifest")
        manifest = build_manifest(
            batch_name=batch_name,
            brand=args.brand,
            raw_dir=raw_dir,
            videos=videos,
            engine=args.engine,
            audience_timezone=args.audience_timezone,
            audience_profile=args.audience_profile,
            whisper_prompt=args.vocab_prompt,
        )

    # Apply CLI --vocab-prompt override even on existing manifest
    if args.vocab_prompt:
        manifest["common"]["whisper_prompt"] = args.vocab_prompt

    save_manifest(manifest_path, manifest)

    # 3. Scaffold per-video project dirs
    print("scaffolding project directories...")
    for v in manifest["videos"]:
        scaffold_project_dir(REPO_ROOT / v["project_dir"])

    if args.skip_transcribe:
        print(f"\nskipping transcription. manifest at: {manifest_path.relative_to(REPO_ROOT)}")
        return

    # 4. Transcribe in parallel — one transcript per project_dir
    print(f"\ntranscribing with engine={args.engine} workers={args.workers}")

    # Use the appropriate API key based on engine
    api_key = load_openai_key() if args.engine == "whisper" else load_elevenlabs_key()
    vocab_prompt = manifest["common"].get("whisper_prompt") if args.engine == "whisper" else None

    from concurrent.futures import ThreadPoolExecutor, as_completed

    only_seqs = set(s.strip() for s in args.only_seq.split(",")) if args.only_seq else None

    pending = []
    for v in manifest["videos"]:
        if only_seqs and v["seq"] not in only_seqs:
            continue
        project_dir = REPO_ROOT / v["project_dir"]
        raw_path = REPO_ROOT / v["raw_path"]
        transcript_out = project_dir / "transcripts" / f"{raw_path.stem}.json"
        if transcript_out.exists():
            # If --only-seq targets this video, force re-transcribe (user wants a re-run)
            if only_seqs:
                transcript_out.unlink()
            else:
                # Mark as transcribed in manifest if not already
                if v["stages"]["transcribed"] is None:
                    v["stages"]["transcribed"] = {
                        "at": now_iso(),
                        "transcript": str(transcript_out.relative_to(REPO_ROOT)),
                        "engine": args.engine,
                        "cached": True,
                    }
                    v["status"] = "transcribed"
                continue
        pending.append(v)

    if not pending:
        print("all videos already transcribed (cache hit)")
    else:
        print(f"transcribing {len(pending)} videos...")

        def _do_one(v: dict) -> tuple[dict, Path | None, str | None]:
            project_dir = REPO_ROOT / v["project_dir"]
            raw_path = REPO_ROOT / v["raw_path"]
            try:
                out = transcribe_one(
                    video=raw_path,
                    edit_dir=project_dir,
                    engine=args.engine,
                    api_key=api_key,
                    language=args.language,
                    vocab_prompt=vocab_prompt,
                    verbose=False,
                )
                return v, out, None
            except Exception as e:
                return v, None, str(e)

        errors = 0
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(_do_one, v) for v in pending]
            for fut in as_completed(futures):
                v, out, err = fut.result()
                if err:
                    errors += 1
                    print(f"  x {v['seq']}  FAILED: {err}")
                    v["stages"]["transcribed"] = {"at": now_iso(), "error": err}
                else:
                    print(f"  + {v['seq']}  →  {out.name}")
                    v["stages"]["transcribed"] = {
                        "at": now_iso(),
                        "transcript": str(out.relative_to(REPO_ROOT)),
                        "engine": args.engine,
                    }
                    v["status"] = "transcribed"
                save_manifest(manifest_path, manifest)

        if errors:
            print(f"\n{errors} videos failed transcription. re-run to retry.")

    # 5. Pack transcripts per project
    print("\npacking transcripts (phrase-level)...")
    pack_errors = 0
    for v in manifest["videos"]:
        if v["status"] != "transcribed":
            continue
        project_dir = REPO_ROOT / v["project_dir"]
        try:
            pack_transcripts(project_dir)
            print(f"  + {v['seq']}  →  {v['project_dir']}/takes_packed.md")
        except Exception as e:
            pack_errors += 1
            print(f"  x {v['seq']}  PACK FAILED: {e}")

    save_manifest(manifest_path, manifest)

    # Best-effort push of the manifest to the web app so /batches shows it
    # without requiring a separate sync step. Silent on failure — the manifest
    # on disk is the source of truth and `npm run batch:sync` can retry later.
    sync_script = Path(__file__).resolve().parent / "batch_sync.py"
    if sync_script.exists() and os.environ.get("VIDEOMAKER_WEB_URL"):
        try:
            subprocess.run(
                [sys.executable, str(sync_script), "--batch", args.batch],
                check=False,
                capture_output=True,
                timeout=30,
            )
        except Exception:
            pass

    print("\n" + "=" * 60)
    print(f"batch init complete")
    print(f"  manifest:    {manifest_path.relative_to(REPO_ROOT)}")
    print(f"  videos:      {len(manifest['videos'])}")
    print(f"  transcribed: {sum(1 for v in manifest['videos'] if v['status'] == 'transcribed')}")
    if pack_errors:
        print(f"  pack errors: {pack_errors}")
    print("\nNext: spawn EDL sub-agents (Phase 3) per video")


if __name__ == "__main__":
    main()
