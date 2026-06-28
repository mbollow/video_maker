"""Read reviewer feedback back from the Freigabeprozess folder.

Scans every subfolder in the OneDrive-synced review directory, reads each
FREIGABE.txt, parses the STATUS line, and prints a grouped report:

    FREIGEGEBEN  — approved, ready to schedule/post
    AENDERN      — reviewer wants changes (notes shown verbatim)
    OFFEN        — not reviewed yet

The .meta.json pointer in each folder maps the feedback back to its batch + seq,
so Claude can translate the free-text notes into the correction shorthand and
re-cut the right video.

Also flags captions_vN.txt the reviewer may have added/edited.

Usage:
    npm run freigabe:check
    python helpers/freigabe_check.py [--batch <name>] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_FREIGABE_DIR = (
    "/Users/marc/Library/CloudStorage/"
    "OneDrive-FreigegebeneBibliotheken–PalstekGmbH/"
    "Palstek GmbH - Gäste - General/Social_Media_Prototyp/Freigabeprozess – Video"
)

KNOWN = {"OFFEN", "FREIGEGEBEN", "AENDERN"}
# tolerate common reviewer spellings
ALIASES = {
    "ÄNDERN": "AENDERN", "AENDERUNG": "AENDERN", "ÄNDERUNG": "AENDERN",
    "FREIGABE": "FREIGEGEBEN", "OK": "FREIGEGEBEN", "FERTIG": "FREIGEGEBEN",
    "PASST": "FREIGEGEBEN",
}


def parse_freigabe(text: str) -> tuple[str, str]:
    """Return (status, notes). Status normalized to KNOWN; notes = free text below."""
    lines = text.splitlines()
    status = "OFFEN"
    status_idx = None
    for i, line in enumerate(lines):
        m = re.match(r"\s*STATUS\s*:\s*(.+?)\s*$", line, re.IGNORECASE)
        if m:
            raw = m.group(1).strip().upper()
            raw = ALIASES.get(raw, raw)
            status = raw if raw in KNOWN else ("AENDERN" if raw else "OFFEN")
            status_idx = i
            break

    # Notes = everything after the separator line that follows STATUS, minus the
    # boilerplate instruction block.
    notes_lines: list[str] = []
    if status_idx is not None:
        body = lines[status_idx + 1:]
        # drop leading separator + instruction block (up to 2nd separator)
        seps = [i for i, l in enumerate(body) if set(l.strip()) == {"="} and len(l.strip()) >= 6]
        if len(seps) >= 2:
            body = body[seps[1] + 1:]
        elif len(seps) == 1:
            body = body[seps[0] + 1:]
        notes_lines = body
    notes = "\n".join(notes_lines).strip()
    # strip residual instruction echoes
    if notes.startswith("Anleitung für Juliana"):
        notes = ""
    return status, notes


def scan(base: Path, only_batch: str | None) -> list[dict]:
    results = []
    for folder in sorted(base.iterdir()):
        if not folder.is_dir():
            continue
        fr_matches = sorted(folder.glob("FREIGABE*.txt"))
        if not fr_matches:
            continue
        fr = fr_matches[0]
        meta = {}
        meta_path = folder / ".meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
        if only_batch and meta.get("batch") != only_batch:
            continue
        status, notes = parse_freigabe(fr.read_text(encoding="utf-8"))
        caption_files = sorted(p.name for p in folder.glob("captions*.txt"))
        edited_captions = [c for c in caption_files if c != "captions.txt"]
        results.append({
            "folder": folder.name,
            "batch": meta.get("batch"),
            "seq": meta.get("seq"),
            "slug": meta.get("slug"),
            "project_dir": meta.get("project_dir"),
            "status": status,
            "notes": notes,
            "edited_captions": edited_captions,
        })
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description="Read reviewer feedback from the Freigabe folder")
    ap.add_argument("--batch", help="Filter to one batch")
    ap.add_argument("--dir", default=os.environ.get("FREIGABE_DIR", DEFAULT_FREIGABE_DIR))
    ap.add_argument("--json", action="store_true", help="Machine-readable output")
    args = ap.parse_args()

    base = Path(args.dir)
    if not base.exists():
        sys.exit(f"Review-Ordner nicht gefunden:\n  {base}\nIst OneDrive synchronisiert?")

    results = scan(base, args.batch)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    if not results:
        print("Keine FREIGABE.txt gefunden. Erst hochladen mit:  npm run freigabe:push -- --batch <name>")
        return

    groups = {"AENDERN": [], "FREIGEGEBEN": [], "OFFEN": []}
    for r in results:
        groups.get(r["status"], groups["OFFEN"]).append(r)

    icon = {"AENDERN": "✏️ ", "FREIGEGEBEN": "✅", "OFFEN": "⏳"}
    print(f"Freigabe-Status  ({base})\n")
    print(f"  ✅ {len(groups['FREIGEGEBEN'])} freigegeben   "
          f"✏️  {len(groups['AENDERN'])} Änderung   "
          f"⏳ {len(groups['OFFEN'])} offen\n")

    for status in ("AENDERN", "FREIGEGEBEN", "OFFEN"):
        for r in groups[status]:
            ref = f"{r['batch']}/{r['seq']}" if r["batch"] else r["folder"]
            print(f"{icon[status]} {r['folder']}   [{ref}]")
            if r["edited_captions"]:
                print(f"     ↳ geänderte Captions: {', '.join(r['edited_captions'])}")
            if status == "AENDERN" and r["notes"]:
                for line in r["notes"].splitlines():
                    print(f"     │ {line}")
            print()

    if groups["AENDERN"]:
        print("→ Für die ✏️-Videos: gib mir den Ordnernamen oder die [batch/seq], "
              "ich übersetze die Anmerkungen ins Korrektur-Shorthand und re-cutte.")


if __name__ == "__main__":
    main()
