#!/usr/bin/env python3
"""
Headless composition + render — the API-driven equivalent of the Phase-4a
composition sub-agent, so the motion-graphics step can run in the cloud worker
without Claude Code in the loop.

Prereq per video (produced by render.py from the EDL):
    projects/<batch>__<seq>/clips/edited.mp4   (cut + loudnorm'd)
    projects/<batch>__<seq>/master.srt         (output-timeline subtitle cues)

It runs an Anthropic tool-use agent loop with the SAME prompt the interactive
sub-agent uses (prompts/composition_subagent.md). Tools:
  - read_file  : brand SKILL.md / colors_and_type.css, edl.json, master.srt, template
  - run_bash   : ffmpeg keyframe-convert, ffprobe, cp logo, npx hyperframes
                 lint/inspect/render, thumbnail_gen.py  (no shell — argv only)
  - write_file : write into projects/<batch>__<seq>/compositions/ ONLY

Then it records the summary + render duration into the manifest and moves the
video to status `composed`/`rendered`.

Usage:
    python compose_gen.py --batch <name>                # all videos with an EDL but no render
    python compose_gen.py --batch <name> --seq 03 07
    python compose_gen.py --batch <name> --force

Requires ANTHROPIC_API_KEY. Mirrors edl_gen.py / caption_gen.py conventions.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transcribe import _load_env_key  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "composition_subagent.md"
TEMPLATE_PATH = Path(__file__).resolve().parent / "composition_templates" / "talking-head-reel.html"

MODEL_DEFAULT = "claude-opus-4-8"
MAX_STEPS = 60            # compositions take more steps than EDLs (build + lint + render)
MAX_FILE_BYTES = 400_000  # templates/HTML are larger than transcripts
BASH_TIMEOUT_S = 900      # a render can take minutes

# No shell is ever invoked. Leading executable must be allow-listed.
#   ffmpeg/ffprobe : keyframe-convert + duration probe
#   npx/node       : hyperframes lint / inspect / render
#   cp             : copy brand logo into compositions/assets
#   python/python3 : thumbnail_gen.py only
BASH_ALLOWED = {"ffmpeg", "ffprobe", "npx", "node", "cp", "python", "python3"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _maybe_sync_to_web(batch_name: str) -> None:
    sync_script = Path(__file__).resolve().parent / "batch_sync.py"
    if not sync_script.exists():
        return
    try:
        subprocess.run([sys.executable, str(sync_script), "--batch", batch_name],
                       check=False, capture_output=True, timeout=30)
    except Exception:
        pass


def _resolve_in_repo(path_str: str) -> Path | None:
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
    tail = ""
    if len(data) > MAX_FILE_BYTES:
        tail = f"\n\n[...truncated, {len(data)} bytes total, showing first {MAX_FILE_BYTES}...]"
        data = data[:MAX_FILE_BYTES]
    try:
        return (data.decode("utf-8") + tail, False)
    except UnicodeDecodeError:
        return (f"ERROR: {raw} is not UTF-8 text (binary file).", True)


def tool_run_bash(args: dict) -> tuple[str, bool]:
    command = str(args.get("command", "")).strip()
    if not command:
        return ("ERROR: empty command.", True)
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return (f"ERROR: could not parse command ({e}). No shell — pass a single argv command.", True)
    if not argv:
        return ("ERROR: empty command.", True)
    exe = Path(argv[0]).name
    if exe not in BASH_ALLOWED:
        return (f"ERROR: '{exe}' is not allowed. Allowed: {sorted(BASH_ALLOWED)}. "
                f"No shell — pipes/redirects/; are unavailable.", True)
    if exe in {"python", "python3"} and not any("thumbnail_gen.py" in a for a in argv):
        return ("ERROR: python may only be used to run thumbnail_gen.py here.", True)
    try:
        proc = subprocess.run(argv, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=BASH_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return (f"ERROR: command timed out after {BASH_TIMEOUT_S}s.", True)
    except Exception as e:
        return (f"ERROR: failed to run command: {e}", True)
    body = f"exit_code: {proc.returncode}\n--- stdout ---\n{proc.stdout or ''}\n--- stderr ---\n{proc.stderr or ''}"
    if len(body) > MAX_FILE_BYTES:
        body = body[:MAX_FILE_BYTES] + "\n[...truncated...]"
    return (body, proc.returncode != 0)


def make_write_file(allowed_dir: Path):
    """Bind write_file to the project's compositions/ dir — the model can't write elsewhere."""
    allowed_dir = allowed_dir.resolve()
    state = {"wrote": []}

    def tool_write_file(args: dict) -> tuple[str, bool]:
        rel = str(args.get("path", "")).strip()
        content = args.get("content")
        if not rel:
            return ("ERROR: 'path' is required (relative to the compositions/ dir).", True)
        if content is None:
            return ("ERROR: 'content' is required.", True)
        if not isinstance(content, str):
            content = json.dumps(content, indent=2, ensure_ascii=False)
        target = (allowed_dir / rel).resolve()
        try:
            target.relative_to(allowed_dir)
        except ValueError:
            return (f"ERROR: '{rel}' escapes the compositions/ dir — refused.", True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        state["wrote"].append(str(target.relative_to(REPO_ROOT)) if _resolve_in_repo(str(target)) else str(target))
        return (f"OK: wrote {len(content)} bytes to {rel}", False)

    return tool_write_file, state


TOOLS = [
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file in the repo (brand SKILL.md / colors_and_type.css, edl.json, master.srt, the template, existing compositions to copy scaffolding from).",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "run_bash",
        "description": (
            "Run ONE command as argv (no shell — no pipes/redirects/;/&&). Allowed: ffmpeg (keyframe-convert the "
            "speaker to all-intra), ffprobe (duration), cp (copy the brand logo into compositions/assets), "
            "npx/node (hyperframes lint | inspect | render), python/python3 (ONLY video-use/helpers/thumbnail_gen.py). "
            "Renders can take minutes."
        ),
        "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
    },
    {
        "name": "write_file",
        "description": (
            "Write a file INTO this video's compositions/ dir (path is relative to it, e.g. 'index.html', "
            "'hyperframes.json', 'meta.json', 'package.json'). Writing outside compositions/ is refused. "
            "Pass the full file content in `content`."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
]

TOOL_FUNCS = {"read_file": tool_read_file, "run_bash": tool_run_bash}


def _ffprobe_duration(path: Path) -> float | None:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=60)
        return round(float(proc.stdout.strip()), 1)
    except Exception:
        return None


def build_inputs_message(*, manifest: dict, video: dict) -> str:
    project_dir = REPO_ROOT / video["project_dir"]
    brand_path = manifest.get("brand_path") or f"brand-guidelines/{manifest.get('brand', 'default')}"
    transcript_rel = video["stages"].get("transcribed", {}).get("transcript")
    transcript_path = (REPO_ROOT / transcript_rel) if transcript_rel else None
    lines = [
        "Build the Hyperframes composition for this video and render the final mp4.",
        "Follow every step and Brand Rule in your instructions. Lint must be 0 errors / 0 warnings before you render.",
        "When finished, reply with ONLY your 2-3 sentence summary (beats added, render duration + file size, any issues).",
        "",
        f"BATCH_NAME: {manifest['batch_name']}",
        f"SEQ: {video['seq']}",
        f"PROJECT_DIR: {project_dir}",
        f"BRAND_PATH: {REPO_ROOT / brand_path}",
        f"EDL_PATH: {project_dir / 'edl.json'}",
        f"TRANSCRIPT_PATH: {transcript_path if transcript_path else '(none)'}",
        f"RENDERED_CUT_PATH: {project_dir / 'clips' / 'edited.mp4'}",
        f"MASTER_SRT_PATH: {project_dir / 'master.srt'}",
        f"TEMPLATE_PATH: {TEMPLATE_PATH}",
        f"FINAL_RENDER_PATH: {project_dir / 'renders' / 'final.mp4'}",
        f"THUMBNAIL_PATH: {REPO_ROOT / 'batches' / manifest['batch_name'] / 'thumbnails' / (video['seq'] + '.jpg')}",
    ]
    directive = (video.get("directive") or "").strip()
    if directive:
        lines += [
            "",
            "USER DIRECTIVE (the creator's intent — let it guide which beats you emphasize):",
            directive,
        ]
    lines += [
        "",
        "Scaffolding to copy (hyperframes.json/meta.json/package.json shapes): "
        f"reuse the compositions/ of any existing project under {REPO_ROOT / 'projects'} "
        "(read one and adapt); if none exists yet, follow the hyperframes skill scaffolding.",
    ]
    return "\n".join(lines)


def generate_for_video(*, client, manifest, video, system_prompt, model, max_steps) -> tuple[str, bool]:
    import anthropic  # noqa: F401
    comps_dir = REPO_ROOT / video["project_dir"] / "compositions"
    write_file, write_state = make_write_file(comps_dir)
    tool_funcs = {**TOOL_FUNCS, "write_file": write_file}

    system = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
    messages = [{"role": "user", "content": build_inputs_message(manifest=manifest, video=video)}]

    last_text = ""
    for _step in range(max_steps):
        resp = client.messages.create(
            model=model, max_tokens=16000, system=system, tools=TOOLS,
            thinking={"type": "adaptive"}, output_config={"effort": "high"}, messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})
        text_now = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        if text_now:
            last_text = text_now
        if resp.stop_reason == "pause_turn":
            continue
        if resp.stop_reason == "refusal":
            return ("[model refused to build the composition]", False)
        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            break
        results = []
        for tu in tool_uses:
            fn = tool_funcs.get(tu.name)
            if fn is None:
                content, is_err = (f"ERROR: unknown tool '{tu.name}'.", True)
            else:
                try:
                    content, is_err = fn(tu.input if isinstance(tu.input, dict) else {})
                except Exception as e:
                    content, is_err = (f"ERROR: tool raised {type(e).__name__}: {e}", True)
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": content, "is_error": is_err})
        messages.append({"role": "user", "content": results})

    final_render = REPO_ROOT / video["project_dir"] / "renders" / "final.mp4"
    return (last_text or "[no summary returned]", final_render.exists())


def apply_to_manifest(video: dict, summary: str) -> None:
    project_dir = video["project_dir"]
    final_render = REPO_ROOT / project_dir / "renders" / "final.mp4"
    duration = _ffprobe_duration(final_render)
    size_mb = round(final_render.stat().st_size / (1024 * 1024), 1) if final_render.exists() else None
    stages = video.setdefault("stages", {})
    stages["composed"] = {
        "at": now_iso(),
        "composition": f"{project_dir}/compositions/index.html",
        "note": summary,
        "engine": "compose_gen (headless API)",
    }
    stages["rendered"] = {
        "at": now_iso(),
        "render": f"{project_dir}/renders/final.mp4",
        "duration_s": duration,
        "file_size_mb": size_mb,
        "thumbnail": f"batches/{video.get('_batch','')}/thumbnails/{video['seq']}.jpg",
    }
    if video.get("status") in ("edl_planned", "composed", "rendered"):
        video["status"] = "rendered"


def needs_compose(video: dict, force: bool) -> bool:
    if force:
        return True
    if (REPO_ROOT / video["project_dir"] / "renders" / "final.mp4").exists():
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="Headless composition + render for a batch (API-driven Phase-4a sub-agent).")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--seq", nargs="*")
    ap.add_argument("--model", default=MODEL_DEFAULT)
    ap.add_argument("--max-steps", type=int, default=MAX_STEPS)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-sync", action="store_true")
    args = ap.parse_args()

    manifest_path = REPO_ROOT / "batches" / args.batch / "manifest.json"
    for required in (manifest_path, PROMPT_PATH, TEMPLATE_PATH):
        if not required.exists():
            print(f"ERROR: missing required file: {required}", file=sys.stderr)
            sys.exit(2)

    api_key = _load_env_key("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set (.env or environment)", file=sys.stderr)
        sys.exit(2)
    try:
        import anthropic
    except ImportError:
        print("ERROR: the 'anthropic' package is required (video-use project deps).", file=sys.stderr)
        sys.exit(2)

    manifest = json.loads(manifest_path.read_text())
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    client = anthropic.Anthropic(api_key=api_key)

    seqs = set(args.seq) if args.seq else None
    todo = []
    for v in manifest.get("videos", []):
        if seqs is not None and v["seq"] not in seqs:
            continue
        edl_exists = (REPO_ROOT / v["project_dir"] / "edl.json").exists()
        cut_exists = (REPO_ROOT / v["project_dir"] / "clips" / "edited.mp4").exists()
        if not edl_exists:
            print(f"  [{v['seq']}] skipped — no edl.json (run edl_gen first)")
            continue
        if not cut_exists:
            print(f"  [{v['seq']}] skipped — no clips/edited.mp4 (run render.py --build-subtitles on the EDL first)")
            continue
        if not needs_compose(v, args.force):
            print(f"  [{v['seq']}] skipped — final render present (use --force)")
            continue
        v["_batch"] = args.batch  # transient, for thumbnail path in apply_to_manifest
        todo.append(v)

    if not todo:
        print("Nothing to do.")
        return

    print(f"composing + rendering {len(todo)} video(s) with model={args.model}\n")
    ok = 0
    for v in todo:
        print(f"  [{v['seq']}] composing {v.get('slug', '')} …")
        try:
            summary, rendered = generate_for_video(
                client=client, manifest=manifest, video=v, system_prompt=system_prompt,
                model=args.model, max_steps=args.max_steps)
        except anthropic.APIError as e:
            print(f"      FAILED — Anthropic API error: {e}")
            continue
        if not rendered:
            print(f"      FAILED — agent finished without a renders/final.mp4")
            print(f"      model said: {summary[:300]}")
            continue
        apply_to_manifest(v, summary)
        v.pop("_batch", None)
        ok += 1
        print(f"      ok → final.mp4 rendered. {summary[:160]}")

    for v in manifest.get("videos", []):
        v.pop("_batch", None)
    manifest["updated_at"] = now_iso()
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\ndone. {ok}/{len(todo)} rendered. manifest updated.")
    if ok and not args.no_sync:
        _maybe_sync_to_web(args.batch)


if __name__ == "__main__":
    main()
