"""Phase 3 of the Karussell pipeline: push a carousel to the review folder.

Mirrors bild_freigabe_push.py, but a carousel is a MULTI-slide unit, so all
slides land together in a per-version subfolder::

    Freigabeprozess – Bilder/
      013_der-recency-effekt/
        .meta.json
        v1/
          01_start.png
          02_01.png
          03_02.png
          …
          99_ende.png
        captions__der-recency-effekt.txt
        FREIGABE__der-recency-effekt.txt

Hard rules (same as elsewhere): captions.txt + FREIGABE.txt written once, never
overwritten; each rebuild lands as v2/ NEXT TO v1/; folders never deleted.

Usage:
    npm run karussell:freigabe:push -- --batch recency-effekt
    python helpers/karussell_freigabe_push.py --batch <name> [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import karussell_common as kc  # noqa: E402
import bild_common as bc  # noqa: E402
from freigabe_push import (  # noqa: E402
    slugify_hook, next_global_number, src_signature, FREIGABE_TEMPLATE,
)

REPO_ROOT = kc.REPO_ROOT


def ordered_slides(manifest: dict) -> list[dict]:
    def key(s):
        if s.get("kind") == "start":
            return (0, 0)
        if s.get("kind") == "end":
            return (2, 0)
        try:
            return (1, int(s.get("seq")))
        except (TypeError, ValueError):
            return (1, 999)
    return sorted([s for s in manifest.get("slides", []) if s.get("render")], key=key)


def slide_filename(ordinal: int, slide: dict) -> str:
    seq = slide.get("seq")
    label = "start" if slide.get("kind") == "start" else ("ende" if slide.get("kind") == "end" else seq)
    return f"{ordinal:02d}_{label}.png"


def build_captions_text(manifest: dict) -> str:
    parts: list[str] = []
    for platform in ("linkedin", "instagram"):
        rec = manifest.get("posts", {}).get(platform, {})
        if not rec.get("enabled") or not rec.get("caption"):
            continue
        parts += ["=" * 60, platform.upper(), "=" * 60, rec["caption"].rstrip()]
        tags = rec.get("hashtags") or []
        if tags:
            parts += ["", " ".join(tags)]
        parts += ["", ""]
    return ("\n".join(parts).rstrip() + "\n") if parts else ""


def push(manifest: dict, base: Path, batch: str, dry_run: bool, allocator: list[int],
         label: str | None = None) -> dict:
    thema = manifest.get("thema") or batch
    slug_base = label or thema
    slides = ordered_slides(manifest)
    if not slides:
        return {"skipped": "keine gerenderten Slides"}

    fr = manifest.get("freigabe") or {}
    folder_name = fr.get("folder")
    if folder_name and (base / folder_name).exists():
        folder = base / folder_name
        created = False
    else:
        number = allocator[0]
        allocator[0] += 1
        folder_name = f"{number:03d}_{slugify_hook(slug_base)}"
        folder = base / folder_name
        created = True

    title = slugify_hook(slug_base, max_len=24)
    versions = [] if created else list(fr.get("versions", []))
    actions: list[str] = []

    if not dry_run:
        folder.mkdir(parents=True, exist_ok=True)

    # --- slide set version (new vN only when any render changed) ---
    cur_sig = max((src_signature(REPO_ROOT / s["render"]) for s in slides
                   if (REPO_ROOT / s["render"]).exists()), default=0)
    last_sig = versions[-1]["sig"] if versions else None
    if not versions or cur_sig > (last_sig or 0):
        vnum = len(versions) + 1
        vdir = folder / f"v{vnum}"
        if not dry_run:
            vdir.mkdir(parents=True, exist_ok=True)
        for i, s in enumerate(slides, start=1):
            src = REPO_ROOT / s["render"]
            if not src.exists():
                continue
            dst = vdir / slide_filename(i, s)
            if not dry_run:
                shutil.copy2(src, dst)
        versions.append({"dir": vdir.name, "sig": cur_sig, "count": len(slides),
                         "at": datetime.now(timezone.utc).isoformat()})
        actions.append(f"{vdir.name}/ ({len(slides)} Slides)")

    # --- captions (write once; new version on change) ---
    captions_text = build_captions_text(manifest)
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

    if not dry_run:
        (folder / ".meta.json").write_text(json.dumps({
            "batch": batch, "kind": "carousel", "folder": folder_name, "thema": thema,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest["freigabe"] = {"folder": folder_name, "versions": versions,
                            "pushed_at": datetime.now(timezone.utc).isoformat()}
    return {"folder": folder_name, "created": created,
            "actions": actions or ["(aktuell, nichts zu tun)"]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Push a carousel to the Freigabe review folder")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--dir", default=None,
                    help="Ziel-Ordner (Default: FREIGABE_KARUSSELL_DIR, sonst FREIGABE_BILDER_DIR)")
    ap.add_argument("--label", default=None,
                    help="Ordner-/Datei-Slug statt Thema (z.B. energie-a-sachlich)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    base = Path(args.dir) if args.dir else Path(kc.freigabe_dir())
    if not args.dry_run and not base.exists():
        sys.exit(f"Review-Ordner nicht gefunden:\n  {base}\n"
                 "OneDrive synchronisiert? Pfad per --dir oder FREIGABE_KARUSSELL_DIR setzen.")

    manifest_path = kc.CAROUSELS_ROOT / args.batch / "manifest.json"
    if not manifest_path.exists():
        sys.exit(f"manifest fehlt: {manifest_path}\nErst: npm run karussell:build -- --batch {args.batch}")
    manifest = json.loads(manifest_path.read_text())

    print(f"Karussell-Freigabe-Push → {base}")
    if args.dry_run:
        print("  (DRY RUN — es wird nichts geschrieben)\n")

    allocator = [next_global_number(base) if base.exists() else 1]
    res = push(manifest, base, args.batch, args.dry_run, allocator, label=args.label)
    if res.get("skipped"):
        print(f"  übersprungen: {res['skipped']}")
    else:
        tag = "neu" if res["created"] else "update"
        print(f"  {res['folder']}  ({tag}): {', '.join(res['actions'])}")

    if not args.dry_run:
        manifest["updated_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nManifest aktualisiert: {manifest_path.relative_to(REPO_ROOT)}")
    print("\nFertig. Juliana füllt die FREIGABE.txt aus. Einlesen: npm run bild:freigabe:check")


if __name__ == "__main__":
    main()
