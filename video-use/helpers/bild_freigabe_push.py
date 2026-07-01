"""Phase 3 of the Bild-Post pipeline: push image posts to the review folder.

Mirrors freigabe_push.py but for single-image posts. For every post in
image-posts/<batch>/manifest.json, create/update one subfolder in the
Bilder review directory (FREIGABE_BILDER_DIR)::

    Freigabeprozess – Bilder/
      012_dein-team-folgt-dir-nicht/
        .meta.json
        bild_v1__dein-team-folgt-dir.png
        captions__dein-team-folgt-dir.txt
        FREIGABE__dein-team-folgt-dir.txt

Hard rules (same as video freigabe): captions.txt + FREIGABE.txt written once,
never overwritten; each new render lands as bild_vN.png NEXT TO the old; folders
never deleted.

Usage:
    npm run bild:freigabe:push -- --batch juni-fuehrung
    python helpers/bild_freigabe_push.py --batch <name> [--dry-run] [--seq 01,03]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bild_common as bc  # noqa: E402
from freigabe_push import (  # noqa: E402
    slugify_hook, next_global_number, src_signature, FREIGABE_TEMPLATE,
)

REPO_ROOT = bc.REPO_ROOT


def short_title(post: dict, max_len: int = 24) -> str:
    return slugify_hook(post.get("text", ""), max_len=max_len)


def build_captions_text(post: dict) -> str:
    parts: list[str] = []
    for platform in ("linkedin", "instagram"):
        rec = post.get("posts", {}).get(platform, {})
        if not rec.get("enabled") or not rec.get("caption"):
            continue
        parts += ["=" * 60, platform.upper(), "=" * 60, rec["caption"].rstrip()]
        tags = rec.get("hashtags") or []
        if tags:
            parts += ["", " ".join(tags)]
        parts += ["", ""]
    return ("\n".join(parts).rstrip() + "\n") if parts else ""


def push_post(post: dict, base: Path, batch: str, dry_run: bool, allocator: list[int]) -> dict:
    seq = post.get("seq")
    fr = post.get("freigabe") or {}

    folder_name = fr.get("folder")
    if folder_name and (base / folder_name).exists():
        folder = base / folder_name
        created = False
    else:
        number = allocator[0]
        allocator[0] += 1
        folder_name = f"{number:03d}_{slugify_hook(post.get('text', ''))}"
        folder = base / folder_name
        created = True

    render_rel = post.get("render")
    if not render_rel:
        return {"seq": seq, "skipped": "kein gerendertes Bild"}
    render_src = REPO_ROOT / render_rel
    if not render_src.exists():
        return {"seq": seq, "skipped": f"Bild fehlt: {render_rel}"}

    title = short_title(post)
    versions = [] if created else list(fr.get("versions", []))
    actions: list[str] = []

    if not dry_run:
        folder.mkdir(parents=True, exist_ok=True)

    # --- bild_vN (new version only when the render changed) ---
    cur_sig = src_signature(render_src)
    last_sig = versions[-1]["src_mtime"] if versions else None
    if not versions or cur_sig > (last_sig or 0):
        vnum = len(versions) + 1
        dst = folder / f"bild_v{vnum}__{title}.png"
        if not dry_run:
            shutil.copy2(render_src, dst)
        versions.append({"file": dst.name, "src": render_rel, "src_mtime": cur_sig,
                         "at": datetime.now(timezone.utc).isoformat()})
        actions.append(dst.name)

    # --- captions (write once; new versions on change) ---
    captions_text = build_captions_text(post)
    if captions_text:
        existing = sorted(folder.glob("captions*.txt")) if folder.exists() else []
        if not existing:
            dst = folder / f"captions__{title}.txt"
            if not dry_run:
                dst.write_text(captions_text, encoding="utf-8")
            actions.append(dst.name)
        elif not dry_run and existing[-1].read_text(encoding="utf-8").strip() != captions_text.strip():
            dst = folder / f"captions_v{len(existing) + 1}__{title}.txt"
            dst.write_text(captions_text, encoding="utf-8")
            actions.append(dst.name)

    # --- FREIGABE (write once, NEVER overwrite) ---
    if not (folder.exists() and any(folder.glob("FREIGABE*.txt"))):
        dst = folder / f"FREIGABE__{title}.txt"
        if not dry_run:
            dst.write_text(FREIGABE_TEMPLATE, encoding="utf-8")
        actions.append(dst.name)

    # --- .meta.json pointer for freigabe:check ---
    if not dry_run:
        (folder / ".meta.json").write_text(json.dumps({
            "batch": batch, "seq": seq, "kind": "image", "folder": folder_name,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    post["freigabe"] = {
        "folder": folder_name, "versions": versions,
        "pushed_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"seq": seq, "folder": folder_name, "created": created,
            "actions": actions or ["(aktuell, nichts zu tun)"]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Push Bild-Posts to the Freigabe review folder")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--dir", default=None,
                    help="Ziel-Ordner (Default: FREIGABE_BILDER_DIR aus .env)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seq", help="Nur diese seq(s), kommagetrennt")
    args = ap.parse_args()

    base = Path(args.dir) if args.dir else Path(bc.env_value("FREIGABE_BILDER_DIR"))
    if not args.dry_run and not base.exists():
        sys.exit(f"Review-Ordner nicht gefunden:\n  {base}\n"
                 "OneDrive synchronisiert? Pfad per --dir oder FREIGABE_BILDER_DIR setzen.")

    manifest_path = REPO_ROOT / "image-posts" / args.batch / "manifest.json"
    if not manifest_path.exists():
        sys.exit(f"manifest fehlt: {manifest_path}\nErst: npm run bild:build -- --batch {args.batch}")
    manifest = json.loads(manifest_path.read_text())

    only = {s.strip() for s in args.seq.split(",")} if args.seq else None
    print(f"Bild-Freigabe-Push → {base}")
    if args.dry_run:
        print("  (DRY RUN — es wird nichts geschrieben)\n")

    allocator = [next_global_number(base) if base.exists() else 1]
    for post in manifest["posts"]:
        if only is not None and str(post.get("seq")) not in only:
            continue
        res = push_post(post, base, args.batch, args.dry_run, allocator)
        if res.get("skipped"):
            print(f"  [{res['seq']}] übersprungen: {res['skipped']}")
        else:
            tag = "neu" if res["created"] else "update"
            print(f"  [{res['seq']}] {res['folder']}  ({tag}): {', '.join(res['actions'])}")

    if not args.dry_run:
        manifest["updated_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nManifest aktualisiert: {manifest_path.relative_to(REPO_ROOT)}")
    print("\nFertig. Juliana füllt pro Bild die FREIGABE.txt aus.")
    print("Rückmeldungen einlesen:  npm run bild:freigabe:check")


if __name__ == "__main__":
    main()
