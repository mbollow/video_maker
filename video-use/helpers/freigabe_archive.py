#!/usr/bin/env python3
"""freigabe_archive.py — veröffentlichte Videos nach /veröffentlicht verschieben + aufräumen.

Ein Video gilt als ONLINE, wenn seine GHL-Posts (aus dem Ledger, per post_id live
abgefragt) `publishedAt` gesetzt haben. ERST DANN wird der Freigabe-Ordner
`NNN_slug/` nach `…/Freigabeprozess – Video/veröffentlicht/NNN_slug/` verschoben —
so ist transparent, welche Videos wirklich online sind.

Beim Verschieben werden die historischen Versionen aufgeräumt:
  BEHALTEN : die online gegangene Endfassung (final_v* mit passendem Ledger-SHA,
             sonst die neueste), das neueste cover*.png, ALLE captions*.txt,
             FREIGABE*.txt, ANTWORT*.txt, .meta.json und die Original-Kameradatei.
  LÖSCHEN  : alle älteren final_v* und älteren cover_v*.

Default = DRY-RUN (zeigt nur an). Mit --execute wird verschoben/gelöscht.

    python freigabe_archive.py                     # DRY-RUN: welche Videos sind online?
    python freigabe_archive.py --execute           # online-Ordner verschieben + aufräumen
    python freigabe_archive.py --folder 003 --execute   # Ordner 003 forcieren (ohne Live-Check)
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ghl_ledger import load_ledger, sha256_file  # noqa: E402
from transcribe import _load_env_key  # noqa: E402
from ghl_client import GHLClient, GHLError  # noqa: E402

FREI = Path(
    "/Users/marc/Library/CloudStorage/OneDrive-FreigegebeneBibliotheken–PalstekGmbH/"
    "Palstek GmbH - Gäste - General/Social_Media_Prototyp/Freigabeprozess – Video"
)
ARCHIVE = FREI / "veröffentlicht"


def _final_num(p: Path) -> int:
    m = re.search(r"final_v(\d+)", p.name)
    return int(m.group(1)) if m else -1


def _media_base(url: str | None) -> str:
    return (url or "").rsplit("/", 1)[-1]


def published_index(client: GHLClient) -> set[tuple[str, str]]:
    """{(media_basename, account_id)} über ALLE veröffentlichten GHL-Posts.

    Robust gegen den GHL-Freigabe-Flow: beim Freigeben/Neu-Schedulen eines Drafts
    entstehen neue post_ids (die alten werden deleted), aber die hochgeladene
    Media-Datei (url) bleibt gleich. Daher matchen wir über Media + Account,
    NICHT über die (evtl. veraltete) post_id aus dem Ledger.
    """
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(days=45)  # nur zuletzt Veröffentlichtes reicht
    idx: set[tuple[str, str]] = set()
    skip = 0
    while skip < 300:  # 3 Seiten x 100 decken viele Wochen Cadence ab
        posts = client.search_posts(post_status="published", limit=100, skip=skip,
                                    from_date=since)
        if not posts:
            break
        for p in posts:
            if not p.get("publishedAt"):
                continue
            bases = {_media_base(m.get("url")) for m in (p.get("media") or [])}
            for a in (p.get("accountIds") or []):
                for b in bases:
                    if b:
                        idx.add((b, a))
        if len(posts) < 100:
            break
        skip += 100
    return idx


def folder_states(ledger: dict, client: GHLClient) -> dict:
    idx = published_index(client)
    by_folder: dict[str, list[dict]] = {}
    for e in ledger.get("entries", []):
        f = e.get("folder") or ""
        if re.match(r"^\d{3}_", f):
            by_folder.setdefault(f, []).append(e)
    out = {}
    for folder, ents in by_folder.items():
        pairs = [(_media_base(e.get("media_url")), a)
                 for e in ents for a in (e.get("account_ids") or [])]
        live = [pr for pr in pairs if pr[0] and pr in idx]
        online = len(pairs) > 0 and len(live) == len(pairs)
        out[folder] = {
            "entries": ents,
            "online": online,
            "n_live": len(live),
            "n_total": len(pairs),
            "shas": {e.get("sha256") for e in ents if e.get("sha256")},
        }
    return out


def prune_and_move(folder: Path, published_shas: set[str], execute: bool) -> dict:
    finals = sorted(folder.glob("final_v*.mp4"))
    keep_finals = {f for f in finals if sha256_file(f) in published_shas}
    if not keep_finals and finals:
        keep_finals = {max(finals, key=_final_num)}
    covers = sorted(folder.glob("cover*.png"))
    keep_covers = {max(covers, key=lambda p: p.stat().st_mtime)} if covers else set()

    to_delete = [f for f in finals if f not in keep_finals] + \
                [c for c in covers if c not in keep_covers]
    for f in to_delete:
        if execute:
            f.unlink()

    dst = ARCHIVE / folder.name
    if execute:
        ARCHIVE.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            return {"error": f"Zielordner existiert schon: {dst}"}
        shutil.move(str(folder), str(dst))
    return {
        "kept": sorted(p.name for p in (keep_finals | keep_covers)),
        "deleted": sorted(p.name for p in to_delete),
        "moved_to": str(dst),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Veröffentlichte Videos archivieren + aufräumen")
    ap.add_argument("--execute", action="store_true", help="Wirklich verschieben/löschen (sonst Dry-Run)")
    ap.add_argument("--folder", help="Bestimmten Ordner NNN forcieren (ohne Live-Check)")
    args = ap.parse_args()

    if not FREI.exists():
        sys.exit(f"Freigabe-Ordner nicht gefunden: {FREI}")
    ledger = load_ledger()

    # --- Force-Modus: einen Ordner ohne Live-Check archivieren ---
    if args.folder:
        cand = [p for p in FREI.iterdir() if p.is_dir() and re.match(rf"^{args.folder}_", p.name)]
        if not cand:
            sys.exit(f"Kein Ordner {args.folder}_* in {FREI}")
        folder = cand[0]
        shas = {e.get("sha256") for e in ledger.get("entries", []) if (e.get("folder") == folder.name)}
        res = prune_and_move(folder, shas, args.execute)
        tag = "VERSCHOBEN" if args.execute else "DRY-RUN"
        print(f"[{args.folder}] {tag} → veröffentlicht/{folder.name}")
        print(f"    behalten: {', '.join(res.get('kept', []))}")
        print(f"    gelöscht: {', '.join(res.get('deleted', [])) or '(nichts)'}")
        if res.get("error"):
            print(f"    FEHLER: {res['error']}")
        return

    # --- Auto-Modus: online-Status live prüfen ---
    client = GHLClient(_load_env_key("GHL_PRIVATE_INTEGRATION_TOKEN"), _load_env_key("GHL_LOCATION_ID"))
    states = folder_states(ledger, client)
    if not states:
        print("Keine Videos im Ledger."); return

    print(f"{'Ordner':<52}{'live/gesamt':<14}{'online?'}")
    print("-" * 76)
    online = []
    for folder, s in sorted(states.items()):
        present = (FREI / folder).is_dir()
        note = "" if present else "  (schon archiviert / verschoben)"
        live = f"{s['n_live']}/{s['n_total']}"
        print(f"{folder[:50]:<52}{live:<14}{'JA' if s['online'] else 'nein'}{note}")
        if s["online"] and present:
            online.append((folder, s))

    if not online:
        print("\nNichts zu archivieren (kein Video vollständig online).")
        return

    print(f"\n{'AUSFÜHREN' if args.execute else 'DRY-RUN — mit --execute wirklich verschieben'}:")
    for folder, s in online:
        res = prune_and_move(FREI / folder, s["shas"], args.execute)
        tag = "verschoben" if args.execute else "würde verschieben"
        print(f"  [{folder[:3]}] {tag} → veröffentlicht/{folder}")
        print(f"       behalten: {', '.join(res.get('kept', []))}")
        print(f"       löschen : {', '.join(res.get('deleted', [])) or '(nichts)'}")
        if res.get("error"):
            print(f"       FEHLER: {res['error']}")


if __name__ == "__main__":
    main()
