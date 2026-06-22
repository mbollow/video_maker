#!/usr/bin/env python3
"""
Headless EDL generation — the API-driven equivalent of the Phase-3 EDL
sub-agent, so the cut step can run in the cloud worker without Claude Code in
the loop.

It runs an Anthropic tool-use agent loop with the SAME prompt the interactive
sub-agent uses (prompts/edl_subagent.md). The model gets three tools:
  - read_file : read the transcript JSON / takes_packed.md / brand files
  - run_bash  : run ffmpeg/ffprobe silencedetect + curl re-scribe + render.py
                verify (no shell — argv only, allow-listed executables)
  - write_edl : validate + write projects/<batch>__<seq>/edl.json

It then writes the model's reasoning summary into the manifest and moves the
video to status `edl_planned` — exactly what the main session did by hand.

Usage:
    python edl_gen.py --batch <name>                # all videos needing an EDL
    python edl_gen.py --batch <name> --seq 03 07    # specific videos
    python edl_gen.py --batch <name> --force        # re-cut even if edl exists

Requires ANTHROPIC_API_KEY (captions/EDL) and, for the re-scribe step,
ELEVENLABS_API_KEY in ./.env (repo root). Mirrors caption_gen.py conventions.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transcribe import _load_env_key  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "edl_subagent.md"

MODEL_DEFAULT = "claude-opus-4-8"
MAX_STEPS = 40           # hard cap on agent-loop iterations per video
MAX_FILE_BYTES = 256_000  # cap a single read_file payload to protect context
BASH_TIMEOUT_S = 300

# run_bash safety: no shell is ever invoked (argv only via shlex), and the
# leading executable must be on this list. ffmpeg/ffprobe for analysis, curl
# for the ElevenLabs re-scribe, python/uv only to run the repo's render.py.
BASH_ALLOWED = {"ffmpeg", "ffprobe", "curl", "python", "python3", "uv"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _maybe_sync_to_web(batch_name: str) -> None:
    """Best-effort manifest push to the web app (same hook as the other helpers)."""
    sync_script = Path(__file__).resolve().parent / "batch_sync.py"
    if not sync_script.exists():
        return
    try:
        subprocess.run(
            [sys.executable, str(sync_script), "--batch", batch_name],
            check=False, capture_output=True, timeout=30,
        )
    except Exception:
        pass


# --------------------------------------------------------------------------
# Tool implementations (client-side). Each returns a string the model reads.
# --------------------------------------------------------------------------

def _resolve_in_repo(path_str: str) -> Path | None:
    """Resolve a path (absolute or repo-relative) and confirm it stays in the repo."""
    p = Path(path_str)
    if not p.is_absolute():
        p = REPO_ROOT / p
    p = p.resolve()
    try:
        p.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return None
    return p


def tool_read_file(args: dict) -> tuple[str, bool]:
    raw = str(args.get("path", "")).strip()
    p = _resolve_in_repo(raw)
    if p is None:
        return (f"ERROR: path '{raw}' is outside the repo and was refused.", True)
    if not p.exists() or not p.is_file():
        return (f"ERROR: no such file: {raw}", True)
    data = p.read_bytes()
    truncated = b""
    if len(data) > MAX_FILE_BYTES:
        truncated = f"\n\n[...truncated, {len(data)} bytes total, showing first {MAX_FILE_BYTES}...]".encode()
        data = data[:MAX_FILE_BYTES]
    try:
        return (data.decode("utf-8") + truncated.decode("utf-8"), False)
    except UnicodeDecodeError:
        return (f"ERROR: {raw} is not UTF-8 text (binary file).", True)


def tool_run_bash(args: dict) -> tuple[str, bool]:
    command = str(args.get("command", "")).strip()
    if not command:
        return ("ERROR: empty command.", True)
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return (f"ERROR: could not parse command ({e}). No shell is available — pass a single argv command.", True)
    if not argv:
        return ("ERROR: empty command.", True)

    exe = Path(argv[0]).name
    if exe not in BASH_ALLOWED:
        return (f"ERROR: '{exe}' is not allowed. Allowed: {sorted(BASH_ALLOWED)}. "
                f"No shell — so pipes/redirects/; are unavailable. "
                f"For render verification call render.py via python.", True)
    if exe in {"python", "python3", "uv"} and not any("render.py" in a for a in argv):
        return ("ERROR: python/uv may only be used to run render.py.", True)
    if exe == "curl" and not any("api.elevenlabs.io" in a for a in argv):
        return ("ERROR: curl is only allowed against api.elevenlabs.io (the re-scribe endpoint).", True)

    try:
        proc = subprocess.run(
            argv, cwd=str(REPO_ROOT), capture_output=True, text=True,
            timeout=BASH_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return (f"ERROR: command timed out after {BASH_TIMEOUT_S}s.", True)
    except Exception as e:
        return (f"ERROR: failed to run command: {e}", True)

    out = proc.stdout or ""
    err = proc.stderr or ""
    # ffmpeg/ffprobe write their useful output (silencedetect, durations) to stderr.
    body = f"exit_code: {proc.returncode}\n--- stdout ---\n{out}\n--- stderr ---\n{err}"
    if len(body) > MAX_FILE_BYTES:
        body = body[:MAX_FILE_BYTES] + "\n[...truncated...]"
    return (body, proc.returncode != 0)


REQUIRED_PADDING_KEYS = {
    "mid_sentence_tail_ms", "mid_sentence_lead_ms",
    "sentence_boundary_tail_ms", "sentence_boundary_lead_ms",
    "video_end_tail_ms",
}


def _validate_edl(edl: dict) -> str | None:
    """Return an error string if the EDL violates the Cut-Standards shape, else None."""
    if not isinstance(edl, dict):
        return "edl must be a JSON object."
    if not isinstance(edl.get("sources"), dict) or not edl["sources"]:
        return "edl.sources must be a non-empty object mapping stem -> relative mp4 path."
    if "grade" not in edl or edl["grade"] is not None:
        return "edl.grade must be present and null (Windows auto-grade is broken)."
    pad = edl.get("_padding_params")
    if not isinstance(pad, dict):
        return "edl._padding_params block is mandatory (no magic numbers in ranges)."
    missing = REQUIRED_PADDING_KEYS - set(pad)
    if missing:
        return f"_padding_params missing required keys: {sorted(missing)}."
    ranges = edl.get("ranges")
    if not isinstance(ranges, list) or not ranges:
        return "edl.ranges must be a non-empty list."
    for i, r in enumerate(ranges):
        if not isinstance(r, dict):
            return f"ranges[{i}] must be an object."
        for k in ("source", "start", "end", "note"):
            if k not in r:
                return f"ranges[{i}] missing required field '{k}' (every range needs a note)."
        if not isinstance(r["start"], (int, float)) or not isinstance(r["end"], (int, float)):
            return f"ranges[{i}].start/end must be numbers (seconds)."
        if r["end"] <= r["start"]:
            return f"ranges[{i}].end ({r['end']}) must be greater than start ({r['start']})."
        if r["source"] not in edl["sources"]:
            return f"ranges[{i}].source '{r['source']}' is not declared in edl.sources."
    return None


def make_write_edl(edl_path: Path):
    """Bind write_edl to a fixed output path so the model can't write elsewhere."""
    state = {"written": False}

    def tool_write_edl(args: dict) -> tuple[str, bool]:
        edl = args.get("edl")
        if isinstance(edl, str):
            try:
                edl = json.loads(edl)
            except json.JSONDecodeError as e:
                return (f"ERROR: 'edl' was a string but not valid JSON: {e}", True)
        err = _validate_edl(edl)
        if err:
            return (f"VALIDATION FAILED: {err} Fix and call write_edl again.", True)
        edl_path.parent.mkdir(parents=True, exist_ok=True)
        edl_path.write_text(json.dumps(edl, indent=2, ensure_ascii=False), encoding="utf-8")
        state["written"] = True
        try:
            shown = edl_path.relative_to(REPO_ROOT)
        except ValueError:
            shown = edl_path
        return (f"OK: wrote {len(edl['ranges'])} ranges to {shown}.", False)

    return tool_write_edl, state


TOOLS = [
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file inside the repo (transcript JSON, takes_packed.md, brand README/tone). Paths are repo-relative or absolute within the repo.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Repo-relative or absolute path inside the repo."}},
            "required": ["path"],
        },
    },
    {
        "name": "run_bash",
        "description": (
            "Run ONE command as argv (no shell, so no pipes/redirects/;/&&). "
            "Allowed executables: ffmpeg, ffprobe (silencedetect + durations), "
            "curl (ONLY to api.elevenlabs.io for the final-word re-scribe), and "
            "python/python3/uv (ONLY to run video-use/helpers/render.py for verification). "
            "ffmpeg/ffprobe diagnostics come back on stderr."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "Single argv command, e.g. ffmpeg -i raw/... -af silencedetect=noise=-30dB:duration=0.25 -f null -"}},
            "required": ["command"],
        },
    },
    {
        "name": "write_edl",
        "description": (
            "Write the final edl.json. Pass the complete EDL object in `edl`. It is validated against the "
            "Cut-Standards shape (sources, grade:null, _padding_params with all required keys, ranges[] each "
            "with a note) before writing. On a validation error, fix and call again. The output path is fixed "
            "to this video's project dir — you do not choose it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"edl": {"type": "object", "description": "The complete EDL JSON object."}},
            "required": ["edl"],
        },
    },
]

TOOL_FUNCS = {"read_file": tool_read_file, "run_bash": tool_run_bash}


def build_inputs_message(*, manifest: dict, video: dict, target_duration) -> str:
    project_dir = REPO_ROOT / video["project_dir"]
    raw_path = REPO_ROOT / video["raw_path"]
    transcript_rel = video["stages"].get("transcribed", {}).get("transcript")
    transcript_path = (REPO_ROOT / transcript_rel) if transcript_rel else None
    packed = project_dir / "takes_packed.md"
    brand_path = manifest.get("brand_path") or f"brand-guidelines/{manifest.get('brand', 'default')}"
    stem = Path(video["raw_path"]).stem

    # The user's per-video directive (Thema / Anweisung / Länge), captured at
    # upload time. If no explicit --target-duration was passed, parse "Länge: N".
    directive = (video.get("directive") or "").strip()
    if target_duration is None and directive:
        m = re.search(r"L[äa]nge\s*[:=]\s*(\d+)", directive)
        if m:
            target_duration = float(m.group(1))

    lines = [
        "Generate the EDL for this single video. Follow every Hard Rule in your instructions.",
        "When finished, call write_edl, then reply with ONLY your 3-5 sentence reasoning summary.",
        "",
        f"BATCH_NAME: {manifest['batch_name']}",
        f"SEQ: {video['seq']}",
        f"RAW_PATH: {raw_path}",
        f"SOURCE_STEM: {stem}  (use this as the key in edl.sources)",
        f"PROJECT_DIR: {project_dir}",
        f"BRAND_PATH: {REPO_ROOT / brand_path}",
        f"TRANSCRIPT_PATH: {transcript_path if transcript_path else '(none — transcript missing!)'}",
        f"PACKED_TRANSCRIPT_PATH: {packed}  (read it first if it exists)",
        f"TARGET_DURATION_S: {target_duration if target_duration is not None else 'null (optimize for tight 40-55s pacing)'}",
    ]
    if directive:
        lines += [
            "",
            "USER DIRECTIVE (the creator's intent for this cut — honor it):",
            directive,
        ]
    lines += [
        "",
        "edl.sources path convention: a relative path FROM the project dir to the raw mp4, "
        f"i.e. \"{Path('../..') / video['raw_path']}\".",
    ]
    return "\n".join(lines)


def generate_for_video(*, client, manifest: dict, video: dict, system_prompt: str,
                       model: str, target_duration, max_steps: int) -> tuple[str, bool]:
    """Run the agent loop for one video. Returns (reasoning_summary, edl_written)."""
    import anthropic

    edl_path = REPO_ROOT / video["project_dir"] / "edl.json"
    write_edl, write_state = make_write_edl(edl_path)
    tool_funcs = {**TOOL_FUNCS, "write_edl": write_edl}

    system = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
    messages = [{"role": "user", "content": build_inputs_message(
        manifest=manifest, video=video, target_duration=target_duration)}]

    last_text = ""
    for _step in range(max_steps):
        resp = client.messages.create(
            model=model,
            max_tokens=16000,
            system=system,
            tools=TOOLS,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})

        # Capture any text the model emitted this turn (the reasoning summary
        # lands on the final end_turn).
        text_now = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        if text_now:
            last_text = text_now

        if resp.stop_reason == "pause_turn":
            continue  # server-tool pause (none here) — re-send to resume
        if resp.stop_reason == "refusal":
            return ("[model refused to produce an EDL]", write_state["written"])

        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            break  # end_turn with no tools → done

        results = []
        for tu in tool_uses:
            fn = tool_funcs.get(tu.name)
            if fn is None:
                content, is_err = (f"ERROR: unknown tool '{tu.name}'.", True)
            else:
                try:
                    content, is_err = fn(tu.input if isinstance(tu.input, dict) else {})
                except Exception as e:  # never let a tool crash the loop
                    content, is_err = (f"ERROR: tool raised {type(e).__name__}: {e}", True)
            results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": content,
                "is_error": is_err,
            })
        messages.append({"role": "user", "content": results})

    return (last_text or "[no reasoning summary returned]", write_state["written"])


def apply_to_manifest(video: dict, reasoning: str) -> None:
    rel_edl = f"{video['project_dir']}/edl.json"
    video.setdefault("stages", {})["edl_planned"] = {
        "at": now_iso(),
        "edl": rel_edl,
        "reasoning_summary": reasoning,
        "engine": "edl_gen (headless API)",
    }
    if video.get("status") in ("transcribed", "edl_planned"):
        video["status"] = "edl_planned"


def needs_edl(video: dict, force: bool) -> bool:
    if force:
        return True
    if video.get("stages", {}).get("edl_planned"):
        return False
    edl_path = REPO_ROOT / video["project_dir"] / "edl.json"
    return not edl_path.exists()


def main() -> None:
    ap = argparse.ArgumentParser(description="Headless EDL generation for a batch (API-driven Phase-3 sub-agent).")
    ap.add_argument("--batch", required=True, help="Batch name under batches/")
    ap.add_argument("--seq", nargs="*", help="Specific 2-digit seqs (e.g. --seq 03 07). Default: all that need an EDL.")
    ap.add_argument("--model", default=MODEL_DEFAULT, help=f"Anthropic model (default {MODEL_DEFAULT})")
    ap.add_argument("--target-duration", type=float, default=None, help="Target duration in seconds (default: tight viral pacing)")
    ap.add_argument("--max-steps", type=int, default=MAX_STEPS, help=f"Max agent-loop steps per video (default {MAX_STEPS})")
    ap.add_argument("--force", action="store_true", help="Re-cut even if an EDL already exists")
    ap.add_argument("--no-sync", action="store_true", help="Skip pushing the manifest to the web app afterwards")
    args = ap.parse_args()

    manifest_path = REPO_ROOT / "batches" / args.batch / "manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: {manifest_path} not found", file=sys.stderr)
        sys.exit(2)
    if not PROMPT_PATH.exists():
        print(f"ERROR: prompt not found: {PROMPT_PATH}", file=sys.stderr)
        sys.exit(2)

    api_key = _load_env_key("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set (.env or environment)", file=sys.stderr)
        sys.exit(2)

    try:
        import anthropic
    except ImportError:
        print("ERROR: the 'anthropic' package is required. Install via the video-use project deps.", file=sys.stderr)
        sys.exit(2)

    manifest = json.loads(manifest_path.read_text())
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    client = anthropic.Anthropic(api_key=api_key)

    seqs = set(args.seq) if args.seq else None
    todo = []
    for v in manifest.get("videos", []):
        if seqs is not None and v["seq"] not in seqs:
            continue
        if not v["stages"].get("transcribed", {}).get("transcript"):
            print(f"  [{v['seq']}] skipped — no transcript yet")
            continue
        if not needs_edl(v, args.force):
            print(f"  [{v['seq']}] skipped — EDL already present (use --force to re-cut)")
            continue
        todo.append(v)

    if not todo:
        print("Nothing to do.")
        return

    print(f"generating EDLs for {len(todo)} video(s) with model={args.model}\n")
    ok = 0
    for v in todo:
        print(f"  [{v['seq']}] cutting {v.get('slug', '')} …")
        try:
            reasoning, written = generate_for_video(
                client=client, manifest=manifest, video=v, system_prompt=system_prompt,
                model=args.model, target_duration=args.target_duration, max_steps=args.max_steps,
            )
        except anthropic.APIError as e:
            print(f"      FAILED — Anthropic API error: {e}")
            continue
        if not written:
            print(f"      FAILED — agent finished without writing a valid edl.json")
            print(f"      model said: {reasoning[:300]}")
            continue
        apply_to_manifest(v, reasoning)
        ok += 1
        print(f"      ok → edl.json written. {reasoning[:160]}")

    manifest["updated_at"] = now_iso()
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\ndone. {ok}/{len(todo)} EDLs generated. manifest updated.")

    if ok and not args.no_sync:
        _maybe_sync_to_web(args.batch)


if __name__ == "__main__":
    main()
