"""Push a batch's videos into the SharePoint/OneDrive review folder (Freigabeprozess).

Phase 6.5 of the batch workflow: for every video in a batch manifest, create
(or update) one subfolder in the OneDrive-synced review directory so a reviewer
(Juliana) can watch original + final, read the captions, and leave notes.

Folder layout per video::

    Freigabeprozess/
      007_dein-bester-mitarbeiter-hat-gekuendigt/
        .meta.json          # batch/seq pointer (hidden, for freigabe:check)
        original.mov        # raw source, untouched
        final_v1.mp4        # the edited cut (v2, v3 ... on re-cut)
        captions.txt        # LinkedIn + Instagram captions
        FREIGABE.txt        # STATUS line + free-text notes (reviewer fills in)

Safety rules (hard):
  * FREIGABE.txt and captions.txt are written ONCE. Never overwritten — that
    would wipe the reviewer's notes. New caption versions land as captions_vN.txt.
  * Each new render lands as final_vN.mp4 NEXT TO the old one. Never overwritten.
  * Folders are never deleted.

The running folder number is GLOBAL across all batches (max existing prefix + 1).
The descriptive slug is derived from the LinkedIn caption hook (first line).

Usage:
    npm run freigabe:push -- --batch 2026-06-21_Büsum_im_Park
    python helpers/freigabe_push.py --batch <name> [--dry-run]

The target directory defaults to the Palstek SharePoint path but can be
overridden with the FREIGABE_DIR environment variable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

from transcribe import env_optional  # noqa: E402  (zentraler .env-Reader mit ${VAR}-Expansion)

# Der OneDrive-Mount wird bei einem Neusync umbenannt — deshalb NIE hartkodieren,
# sondern zentral aus der .env auflösen (siehe ONEDRIVE_SOCIAL_ROOT). Reihenfolge:
#   1. der spezifische FREIGABE_*_DIR-Eintrag,
#   2. sonst aus ONEDRIVE_SOCIAL_ROOT + Unterordner abgeleitet,
#   3. als allerletzter Notnagel der (evtl. veraltete) Alt-Pfad.
_STALE_ROOT = (
    "/Users/marc/Library/CloudStorage/OneDrive-FreigegebeneBibliotheken–PalstekGmbH/"
    "Palstek GmbH - Gäste - General/Social_Media_Prototyp"
)


def _resolve_freigabe(key: str, subfolder: str) -> str:
    val = env_optional(key)
    if val:
        return val
    root = env_optional("ONEDRIVE_SOCIAL_ROOT")
    return str(Path(root or _STALE_ROOT) / subfolder)


DEFAULT_FREIGABE_DIR = _resolve_freigabe("FREIGABE_VIDEO_DIR", "Freigabeprozess – Video")

# Testimonial-Videos sind ein voellig anderer Prozess (Langform, Website-Embed statt
# Social-Post) und haben deshalb einen eigenen Freigabe-Ordner. Ueberschreibbar mit
# der Umgebungsvariable FREIGABE_TESTIMONIAL_DIR. Achtung: normaler Bindestrich " - ",
# NICHT der Halbgeviantstrich " – " der anderen Freigabe-Ordner.
DEFAULT_TESTIMONIAL_FREIGABE_DIR = _resolve_freigabe(
    "FREIGABE_TESTIMONIAL_DIR", "Freigabeprozess - Testimonial")

FREIGABE_TEMPLATE = """STATUS: OFFEN
============================================================
Veröffentlichen auf?   (x = ja — einfach ein x in die Klammer setzen)
  [x] Instagram   — immer aktiv (Standard, bitte so lassen)
  [ ] LinkedIn    — ankreuzen, wenn zusätzlich auf LinkedIn gewünscht
============================================================
Anleitung für Juliana / Michael:
  - Wenn alles passt: ersetze in Zeile 1  OFFEN  durch  FREIGEGEBEN
  - Wenn etwas geändert werden soll: ersetze  OFFEN  durch  AENDERN
    und schreibe deine Anmerkungen einfach hier unten drunter.
  - Du kannst die Datei ganz normal speichern. Das war's.
============================================================

"""

_UMLAUT_MAP = {
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "Ä": "ae", "Ö": "oe", "Ü": "ue",
}


def slugify_hook(text: str, max_len: int = 48) -> str:
    """Turn a caption hook line into a filesystem-safe slug."""
    text = (text or "").strip().splitlines()[0] if text and text.strip() else ""
    for k, v in _UMLAUT_MAP.items():
        text = text.replace(k, v)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0]
    return text or "video"


def short_title(video: dict, max_len: int = 24) -> str:
    """Short kebab slug (≈3 words) appended to file names so they aren't all
    generic (final_v1.mp4, FREIGABE.txt ...) when viewed out of folder context."""
    return slugify_hook(caption_hook(video), max_len=max_len)


def next_global_number(base: Path) -> int:
    """Highest NNN_ folder prefix across the whole review dir, plus one.

    Scannt auch den `veröffentlicht/`-Unterordner mit, damit bereits archivierte
    (veröffentlichte) Videos ihre Nummer behalten und keine Nummer doppelt vergeben wird.
    """
    highest = 0
    dirs_to_scan = []
    if base.exists():
        dirs_to_scan.append(base)
        published = base / "veröffentlicht"
        if published.exists():
            dirs_to_scan.append(published)
    for d in dirs_to_scan:
        for child in d.iterdir():
            m = re.match(r"^(\d{3,})_", child.name)
            if child.is_dir() and m:
                highest = max(highest, int(m.group(1)))
    return highest + 1


def caption_hook(video: dict) -> str:
    li = video.get("posts", {}).get("linkedin", {})
    cap = li.get("caption")
    if cap:
        return cap
    ig = video.get("posts", {}).get("instagram", {})
    return ig.get("caption") or video.get("slug") or "video"


def build_captions_text(video: dict) -> str:
    parts: list[str] = []
    for platform in ("linkedin", "instagram"):
        post = video.get("posts", {}).get(platform, {})
        if not post.get("enabled"):
            continue
        caption = post.get("caption")
        if not caption:
            continue
        parts.append("=" * 60)
        parts.append(platform.upper())
        parts.append("=" * 60)
        parts.append(caption.rstrip())
        hashtags = post.get("hashtags") or []
        if hashtags:
            parts.append("")
            parts.append(" ".join(hashtags))
        parts.append("")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n" if parts else ""


def src_signature(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def push_video(video: dict, base: Path, dry_run: bool, allocator: list[int]) -> dict:
    """Create/update one review subfolder. Returns a result dict for logging.

    ``allocator`` is a single-element list holding the next free global number;
    it is bumped here so numbering stays correct even in --dry-run (when folders
    are not actually created on disk).
    """
    seq = video.get("seq")
    fr = video.get("freigabe") or {}

    # Resolve folder (reuse existing on re-push; assign new global number once).
    folder_name = fr.get("folder")
    if folder_name and (base / folder_name).exists():
        folder = base / folder_name
        created = False
    else:
        number = allocator[0]
        allocator[0] += 1
        slug = slugify_hook(caption_hook(video))
        folder_name = f"{number:03d}_{slug}"
        folder = base / folder_name
        created = True

    final_rel = (video.get("stages", {}).get("rendered") or {}).get("final")
    if not final_rel:
        return {"seq": seq, "skipped": "kein gerenderter final.mp4"}
    final_src = REPO_ROOT / final_rel
    if not final_src.exists():
        return {"seq": seq, "skipped": f"final fehlt: {final_rel}"}

    raw_rel = video.get("raw_path")
    raw_src = (REPO_ROOT / raw_rel) if raw_rel else None

    actions: list[str] = []
    # A freshly assigned folder starts with no versions, even if the manifest
    # carries a stale `versions` list from an earlier push to a different dir.
    versions = [] if created else list(fr.get("versions", []))
    cur_sig = src_signature(final_src)
    title = short_title(video)  # kebab suffix appended to non-original file names

    if not dry_run:
        folder.mkdir(parents=True, exist_ok=True)

    # --- original (once) — keep the camera file name so the source is identifiable ---
    if raw_src and raw_src.exists():
        already = folder.exists() and any(folder.glob("original*"))
        if not already:
            orig_dst = folder / f"original – {raw_src.stem}{raw_src.suffix.lower()}"
            if not dry_run:
                shutil.copy2(raw_src, orig_dst)
            actions.append(orig_dst.name)

    # --- final_vN (new version only when the render changed) ---
    last_sig = versions[-1]["src_mtime"] if versions else None
    if not versions or cur_sig > (last_sig or 0):
        vnum = len(versions) + 1
        final_dst = folder / f"final_v{vnum}__{title}.mp4"
        if not dry_run:
            shutil.copy2(final_src, final_dst)
        versions.append({
            "file": final_dst.name,
            "src": final_rel,
            "src_mtime": cur_sig,
            "at": datetime.now(timezone.utc).isoformat(),
        })
        actions.append(final_dst.name)

    # --- captions: NUR einmalig seeden, wenn noch KEINE Caption existiert. ---
    # Die Captions im Freigabe-Ordner sind handgepflegt (Wahrheit). Ein Re-Push
    # darf sie NIE überschreiben und auch KEINE captions_vN aus dem Manifest anlegen
    # (das Manifest weicht bewusst vom handgepflegten Text ab). Also: nur seeden,
    # damit ein brandneues Video überhaupt eine Datei zum Bearbeiten hat.
    existing_caps = sorted(folder.glob("captions*.txt")) if folder.exists() else []
    if not existing_caps:
        captions_text = build_captions_text(video)
        if captions_text:
            cap_dst = folder / f"captions__{title}.txt"
            if not dry_run:
                cap_dst.write_text(captions_text, encoding="utf-8")
            actions.append(cap_dst.name)

    # --- cover_vN.png (Reel-Titelbild; write once, neue Version bei Änderung) ---
    # Quelle: neuestes cover_v*.png im renders-Ordner des Projekts (aus cover_build.py).
    cover_srcs = sorted(final_src.parent.glob("cover_v*.png"))
    if cover_srcs:
        cover_src = cover_srcs[-1]
        existing_covers = sorted(folder.glob("cover*.png")) if folder.exists() else []
        if not existing_covers:
            cover_dst = folder / f"cover__{title}.png"
            if not dry_run:
                shutil.copy2(cover_src, cover_dst)
            actions.append(cover_dst.name)
        elif src_signature(cover_src) > src_signature(existing_covers[-1]):
            # copy2 erhält mtime -> neuerer Cover-Frame = neuere mtime als die Kopie
            cover_dst = folder / f"cover_v{len(existing_covers) + 1}__{title}.png"
            if not dry_run:
                shutil.copy2(cover_src, cover_dst)
            actions.append(cover_dst.name)

    # --- FREIGABE (write once, NEVER overwrite) ---
    freigabe_exists = folder.exists() and any(folder.glob("FREIGABE*.txt"))
    if not freigabe_exists:
        freigabe_file = folder / f"FREIGABE__{title}.txt"
        if not dry_run:
            freigabe_file.write_text(FREIGABE_TEMPLATE, encoding="utf-8")
        actions.append(freigabe_file.name)

    # --- .meta.json pointer for freigabe:check ---
    if not dry_run:
        (folder / ".meta.json").write_text(json.dumps({
            "batch": video.get("_batch"),
            "seq": seq,
            "slug": video.get("slug"),
            "project_dir": video.get("project_dir"),
            "folder": folder_name,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    # write-back into manifest video
    video["freigabe"] = {
        "folder": folder_name,
        "versions": versions,
        "pushed_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "seq": seq,
        "folder": folder_name,
        "created": created,
        "actions": actions or ["(aktuell, nichts zu tun)"],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Push batch videos to the Freigabe review folder")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--dir", default=os.environ.get("FREIGABE_DIR", DEFAULT_FREIGABE_DIR),
                    help="Target review directory (default: Palstek SharePoint / FREIGABE_DIR)")
    ap.add_argument("--dry-run", action="store_true", help="Show what would happen, write nothing")
    ap.add_argument("--seq", help="Nur diese seq(s) pushen, kommagetrennt (z.B. 01 oder 01,03). Default: alle")
    args = ap.parse_args()

    only_seqs = {s.strip() for s in args.seq.split(",")} if args.seq else None

    base = Path(args.dir)
    if not args.dry_run and not base.exists():
        sys.exit(
            f"Review-Ordner nicht gefunden:\n  {base}\n"
            "Ist OneDrive synchronisiert? Pfad per --dir oder FREIGABE_DIR setzen."
        )

    manifest_path = REPO_ROOT / "batches" / args.batch / "manifest.json"
    if not manifest_path.exists():
        sys.exit(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())

    print(f"Freigabe-Push → {base}")
    if args.dry_run:
        print("  (DRY RUN — es wird nichts geschrieben)\n")

    allocator = [next_global_number(base) if base.exists() else 1]
    for video in manifest["videos"]:
        if only_seqs is not None and str(video.get("seq")) not in only_seqs:
            continue
        video["_batch"] = args.batch
        res = push_video(video, base, args.dry_run, allocator)
        video.pop("_batch", None)
        if res.get("skipped"):
            print(f"  [{res['seq']}] übersprungen: {res['skipped']}")
        else:
            tag = "neu" if res["created"] else "update"
            print(f"  [{res['seq']}] {res['folder']}  ({tag}): {', '.join(res['actions'])}")

    if not args.dry_run:
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nManifest aktualisiert: {manifest_path}")
    print("\nFertig. Juliana kann jetzt im Ordner pro Video die FREIGABE.txt ausfüllen.")
    print("Rückmeldungen später einlesen mit:  npm run freigabe:check")


if __name__ == "__main__":
    main()
