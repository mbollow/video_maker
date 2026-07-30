"""Sync hand-curated captions from the Freigabe folders INTO the batch manifests.

The captions__*.txt files in each Freigabe review folder are the single source of
truth for post copy — Juliana/Michael edit them by hand after review. The batch
manifest may still carry the older, auto-generated caption. This helper copies the
folder text back into the manifest so the manifest mirrors the truth.

Wired to run automatically at the start of `ghl_plan.py` (before any GHL upload),
so the manifest is always in sync before we post. Also runnable standalone:

    python helpers/ghl_sync_captions.py                 # sync all video folders
    python helpers/ghl_sync_captions.py --batch <name>  # only one batch
    python helpers/ghl_sync_captions.py --dry-run

The GHL planner itself reads the folder txt directly, so this does NOT change what
gets posted — it keeps the manifest (the central record, also pushed to the web app)
faithful to the hand-edited text.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ghl_push import _extract_caption_section  # noqa: E402
from freigabe_push import DEFAULT_FREIGABE_DIR  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VIDEO_AREA = Path(DEFAULT_FREIGABE_DIR)  # …/Freigabeprozess – Video

# Platforms that have their own block in a captions file and their own manifest post.
SYNC_PLATFORMS = ("linkedin", "instagram")


def newest_caption_file(folder: Path) -> Path | None:
    """Return the NEWEST captions file in a folder.

    Files are named `captions__<title>.txt` (v1) and `captions_v<N>__<title>.txt`
    for later versions. Plain `sorted()[0]` would pick the v1 file (because '_' < 'v'),
    i.e. the OLDEST — so we rank by explicit version number, v1 for the base file.
    """
    caps = list(folder.glob("captions*.txt"))
    if not caps:
        return None

    def version(p: Path) -> int:
        m = re.search(r"captions_v(\d+)__", p.name)
        return int(m.group(1)) if m else 1

    return max(caps, key=version)


def split_caption_hashtags(block: str) -> tuple[str, list[str]]:
    """Split a platform block into (caption_body, hashtags) — trailing #-only lines."""
    lines = block.rstrip().split("\n")
    hashtags: list[str] = []
    while lines:
        last = lines[-1].strip()
        if last == "":
            lines.pop()
            continue
        toks = last.split()
        if toks and all(t.startswith("#") for t in toks):
            hashtags = toks + hashtags  # keep order when multiple #-lines stack
            lines.pop()
            continue
        break
    caption = "\n".join(lines).rstrip()
    seen: set[str] = set()
    deduped: list[str] = []
    for t in hashtags:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return caption, deduped


def parse_sections(raw: str) -> dict[str, dict]:
    """Parse a captions.txt into {platform: {caption, hashtags}} for known platforms."""
    out: dict[str, dict] = {}
    for platform in SYNC_PLATFORMS:
        block = _extract_caption_section(raw, platform.upper())
        if not block:
            continue
        caption, hashtags = split_caption_hashtags(block)
        if caption:
            out[platform] = {"caption": caption, "hashtags": hashtags}
    return out


def _meta_for(folder: Path) -> dict | None:
    meta_path = folder / ".meta.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def sync_video_area(area: Path = VIDEO_AREA, *, only_batch: str | None = None,
                    dry_run: bool = False, verbose: bool = True) -> dict:
    """Sync every video Freigabe folder's newest captions.txt into its batch manifest.

    Groups updates per manifest so each file is read/written once. Returns a summary
    dict {updated: int, folders: int, skipped: int}.
    """
    if not area.exists():
        if verbose:
            print(f"[ghl-sync] Freigabe-Video-Ordner nicht gefunden: {area}")
        return {"updated": 0, "folders": 0, "skipped": 0}

    # folder -> (batch, seq, sections)
    per_manifest: dict[Path, list[tuple[str, str, dict]]] = {}
    folders = 0
    skipped = 0
    for folder in sorted(p for p in area.iterdir() if p.is_dir()):
        meta = _meta_for(folder)
        if not meta or not meta.get("batch") or not meta.get("seq"):
            continue
        if only_batch and meta["batch"] != only_batch:
            continue
        cap = newest_caption_file(folder)
        if not cap:
            continue
        sections = parse_sections(cap.read_text(encoding="utf-8"))
        if not sections:
            skipped += 1
            continue
        folders += 1
        mpath = REPO_ROOT / "batches" / meta["batch"] / "manifest.json"
        per_manifest.setdefault(mpath, []).append((meta["batch"], str(meta["seq"]), sections))

    updated = 0
    for mpath, jobs in per_manifest.items():
        if not mpath.exists():
            if verbose:
                print(f"[ghl-sync] Manifest fehlt, übersprungen: {mpath}")
            continue
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        by_seq = {str(v.get("seq")): v for v in manifest.get("videos", [])}
        changed = False
        for _batch, seq, sections in jobs:
            video = by_seq.get(seq)
            if not video:
                if verbose:
                    print(f"[ghl-sync] seq {seq} nicht im Manifest {mpath.parent.name}")
                continue
            posts = video.setdefault("posts", {})
            for platform, data in sections.items():
                post = posts.setdefault(platform, {})
                old_cap = post.get("caption")
                old_ht = post.get("hashtags") or []
                if old_cap == data["caption"] and old_ht == data["hashtags"]:
                    continue
                post["caption"] = data["caption"]
                post["hashtags"] = data["hashtags"]
                changed = True
                updated += 1
                if verbose:
                    head = data["caption"].splitlines()[0][:60] if data["caption"] else ""
                    print(f"[ghl-sync] {mpath.parent.name} seq {seq} {platform}: aktualisiert "
                          f"| {head!r}")
        if changed and not dry_run:
            tmp = mpath.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(mpath)

    if verbose:
        tag = " (DRY-RUN)" if dry_run else ""
        print(f"[ghl-sync] {updated} Caption(s) in {len(per_manifest)} Manifest(en) "
              f"aus {folders} Ordner(n) synchronisiert{tag}.")
    return {"updated": updated, "folders": folders, "skipped": skipped}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Sync hand-edited Freigabe captions.txt into the batch manifests")
    ap.add_argument("--batch", help="Nur diesen Batch synchronisieren (default: alle Video-Ordner)")
    ap.add_argument("--dir", default=str(VIDEO_AREA),
                    help="Freigabe-Video-Ordner (default: FREIGABE_DIR)")
    ap.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nichts schreiben")
    args = ap.parse_args()
    sync_video_area(Path(args.dir), only_batch=args.batch, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
