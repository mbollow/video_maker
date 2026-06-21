"""Orchestration helper: "What needs to happen next in this batch?"

Reads the manifest and prints structured guidance for the main Claude
session: which videos need EDL sub-agents, which need composition+render,
whether caption_gen / schedule_plan / review / push is the next move.

Designed to be re-readable across sessions — drop into a fresh chat,
run this, and Claude immediately knows where to pick up.

Usage:
    python helpers/batch_next.py --batch <name>
    python helpers/batch_next.py --batch <name> --json    # machine-readable
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text())


def collect_state(manifest: dict) -> dict:
    """Bucket videos by what they need next."""
    buckets = {
        "needs_transcription": [],   # status == created, no transcript
        "needs_edl":           [],   # transcribed but no edl_planned
        "needs_render":        [],   # edl_planned but no rendered
        "needs_caption":       [],   # rendered but no captioned
        "needs_schedule":      [],   # captioned but no scheduled (or no scheduled_at on any post)
        "ready_for_review":    [],   # scheduled, no posted yet
        "ready_for_push":      [],   # review approved (heuristic: has scheduled posts)
        "completed":           [],   # all enabled posts pushed
    }
    for v in manifest["videos"]:
        s = v["stages"]
        if not s.get("transcribed"):
            buckets["needs_transcription"].append(v["seq"])
        elif not s.get("edl_planned"):
            buckets["needs_edl"].append(v["seq"])
        elif not s.get("rendered"):
            buckets["needs_render"].append(v["seq"])
        elif not s.get("captioned"):
            buckets["needs_caption"].append(v["seq"])
        elif not s.get("scheduled"):
            buckets["needs_schedule"].append(v["seq"])
        else:
            # Has all 6 stages → ready for review / push
            enabled = [p for p, post in v["posts"].items() if post.get("enabled")]
            all_pushed = all(v["posts"][p].get("status") == "pushed" for p in enabled)
            if all_pushed and enabled:
                buckets["completed"].append(v["seq"])
            else:
                buckets["ready_for_review"].append(v["seq"])
                buckets["ready_for_push"].append(v["seq"])
    return buckets


def recommend(buckets: dict, batch_name: str) -> list[dict]:
    """Return ordered list of recommended actions."""
    actions = []
    if buckets["needs_transcription"]:
        actions.append({
            "step": "transcribe",
            "videos": buckets["needs_transcription"],
            "command": f"uv run --project ./video-use python ./video-use/helpers/batch_init.py --batch {batch_name}",
            "agentic": False,
            "explanation": "Some videos still need transcription — re-run batch_init (idempotent).",
        })
    if buckets["needs_edl"]:
        actions.append({
            "step": "edl",
            "videos": buckets["needs_edl"],
            "agentic": True,
            "parallel_workers": 4,
            "prompt_template": "video-use/helpers/prompts/edl_subagent.md",
            "explanation": (
                f"Spawn up to 4 parallel sub-agents using prompts/edl_subagent.md, "
                f"one per video seq. Each writes projects/<batch>__<seq>/edl.json + "
                f"returns a 3-5 sentence reasoning summary. Main session writes the "
                f"summary to manifest.videos[i].stages.edl_planned.reasoning_summary."
            ),
        })
    if buckets["needs_render"]:
        actions.append({
            "step": "compose_render",
            "videos": buckets["needs_render"],
            "agentic": True,
            "parallel_workers": 3,
            "prompt_template": "video-use/helpers/prompts/composition_subagent.md",
            "explanation": (
                f"Spawn up to 3 parallel sub-agents using prompts/composition_subagent.md, "
                f"one per video seq. Each fills the talking-head-reel.html template, "
                f"renders via hyperframes, generates thumbnail."
            ),
        })
    if buckets["needs_caption"]:
        actions.append({
            "step": "caption",
            "videos": buckets["needs_caption"],
            "agentic": False,
            "command": f"uv run --project ./video-use python ./video-use/helpers/caption_gen.py --batch {batch_name}",
            "explanation": "Generate per-platform captions via Anthropic API (one call per video).",
        })
    if buckets["needs_schedule"]:
        actions.append({
            "step": "schedule",
            "videos": buckets["needs_schedule"],
            "agentic": False,
            "command": f"uv run --project ./video-use python ./video-use/helpers/schedule_plan.py --batch {batch_name}",
            "explanation": "Run deterministic slot allocator (DACH CET-aware).",
        })
    if buckets["ready_for_review"] and not actions:
        # All upstream stages done → next is review
        actions.append({
            "step": "review",
            "videos": buckets["ready_for_review"],
            "agentic": False,
            "command": f"uv run --project ./video-use python ./video-use/helpers/review_dashboard.py --batch {batch_name} --open",
            "explanation": "Open review.html in browser. User OK's or provides corrections.",
        })
        actions.append({
            "step": "apply_corrections (optional, if user gave feedback)",
            "videos": [],
            "agentic": False,
            "command": f"echo '<corrections>' | uv run --project ./video-use python ./video-use/helpers/apply_corrections.py --batch {batch_name}",
            "explanation": "Pipe in shorthand corrections from user.",
        })
        actions.append({
            "step": "push (after review approval) — PRIMARY: Metricool MCP",
            "videos": buckets["ready_for_review"],
            "agentic": True,
            "prompt_template": "video-use/helpers/prompts/metricool_push_orchestration.md",
            "explanation": (
                "FIRST RUN: tell Claude 'Push batch <name> via Metricool — draft mode' "
                "→ Claude orchestrates per-video × per-platform via mcp__metricool__* tools "
                "based on metricool_push_orchestration.md. Verify drafts in Metricool UI, "
                "then re-run live without 'draft mode'."
            ),
        })
        actions.append({
            "step": "push (FALLBACK) — Postiz",
            "videos": buckets["ready_for_review"],
            "agentic": False,
            "command": f"uv run --project ./video-use python ./video-use/helpers/postiz_push.py --batch {batch_name} --draft-mode",
            "explanation": "Use only if Metricool unavailable OR user prefers self-hosted. --draft-mode for first run.",
        })
    if buckets["completed"]:
        actions.append({
            "step": "completed",
            "videos": buckets["completed"],
            "explanation": f"{len(buckets['completed'])} videos already fully pushed.",
        })
    return actions


def main() -> None:
    ap = argparse.ArgumentParser(description="What's next for this batch?")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    args = ap.parse_args()

    manifest_path = REPO_ROOT / "batches" / args.batch / "manifest.json"
    if not manifest_path.exists():
        sys.exit(f"manifest not found: {manifest_path}")

    manifest = load_manifest(manifest_path)
    buckets = collect_state(manifest)
    actions = recommend(buckets, args.batch)

    if args.json:
        print(json.dumps({"batch": args.batch, "buckets": buckets, "next_actions": actions}, indent=2))
        return

    print(f"\nBATCH: {args.batch}")
    print(f"  videos total: {len(manifest['videos'])}")
    print()
    print("CURRENT STATE:")
    for bucket, seqs in buckets.items():
        if seqs:
            print(f"  {bucket:24s} {len(seqs):>3}  ({', '.join(seqs)})")

    if not actions:
        print("\nnothing to do — batch fully complete")
        return

    print("\nNEXT ACTIONS (in order):")
    for i, a in enumerate(actions, start=1):
        print(f"\n  [{i}] {a['step'].upper()}")
        if a.get("agentic"):
            print(f"      → AGENTIC ({a.get('parallel_workers', '?')} parallel sub-agents)")
            print(f"      → prompt: {a.get('prompt_template')}")
            print(f"      → seqs: {', '.join(a['videos'])}")
        else:
            if a.get("command"):
                print(f"      $ {a['command']}")
            if a.get("videos"):
                print(f"      seqs: {', '.join(a['videos'])}")
        print(f"      {a['explanation']}")


if __name__ == "__main__":
    main()
