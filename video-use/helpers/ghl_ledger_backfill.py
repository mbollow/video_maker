#!/usr/bin/env python3
"""ghl_ledger_backfill.py — Ledger gegen die Realität in GHL abgleichen.

Warum es das gibt
-----------------
`freigabe_archive.py` erkennt „ist online" ausschliesslich über den Ledger:
es matcht (Media-Basename, Account) gegen die veröffentlichten GHL-Posts.
Zwei Löcher haben schon zweimal dazu geführt, dass ein längst online
gegangener Ordner im Freigabe-Ordner liegen blieb:

  1. **Ledger-Eintrag fehlt ganz.** Der Post wurde terminiert, ohne dass
     `ghl_push.py` gelaufen ist (z. B. von Hand im GHL-UI) — der Archiv-Lauf
     kennt den Ordner dann überhaupt nicht.
  2. **Media-URL veraltet.** Wird ein Draft im GHL-UI scharf gestellt, lädt
     GHL die Dateien neu hoch. Der Post ist derselbe, die Media-URL eine
     andere — der Match läuft ins Leere (typisch für Karussells).

Beides lässt sich unabhängig vom Ledger auflösen: die **Dateigrösse** der in
GHL liegenden Media (per HTTP HEAD) ist gegen die lokalen Dateien im
Freigabe-Ordner eindeutig genug, um Post → Ordner zuzuordnen.

Was es tut
----------
- holt alle veröffentlichten GHL-Posts der letzten `--days` Tage,
- ermittelt je Post die Grösse des ersten Mediums (HEAD, gecacht pro URL),
- ordnet sie über die Grösse einer lokalen Datei zu
  (Video: `final_v*.mp4`, Karussell: `vN/01_start.png`) — im aktiven
  Freigabe-Ordner **und** in `veröffentlicht/`,
- ergänzt fehlende Ledger-Einträge und zieht veraltete Media-URLs/Post-IDs nach.

Default = DRY-RUN. Mit `--execute` wird der Ledger geschrieben (git-getrackt,
committen bleibt Sache des Nutzers).

    uv run python video-use/helpers/ghl_ledger_backfill.py
    uv run python video-use/helpers/ghl_ledger_backfill.py --execute
    uv run python video-use/helpers/ghl_ledger_backfill.py --days 90 --area video
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from freigabe_archive import AREAS, area_base  # noqa: E402
from ghl_client import GHLClient  # noqa: E402
from ghl_ledger import load_ledger, save_ledger, sha256_file  # noqa: E402
from transcribe import _load_env_key  # noqa: E402


# --------------------------------------------------------------------------- #
# Lokale Kandidaten: welche Datei eines Freigabe-Ordners landet in GHL?
# --------------------------------------------------------------------------- #

def _final_num(p: Path) -> int:
    m = re.search(r"final_v(\d+)", p.name)
    return int(m.group(1)) if m else -1


def _version_num(p: Path) -> int:
    """Versionsnummer einer Kandidaten-Datei (`final_v7…mp4` → 7, `v8/01_start.png` → 8)."""
    m = re.search(r"final_v(\d+)", p.name) or re.fullmatch(r"v(\d+)", p.parent.name)
    return int(m.group(1)) if m else -1


def local_candidates(area: str) -> dict[int, list[tuple[Path, Path, bool, bool]]]:
    """{dateigroesse: [(freigabe_ordner, datei, archiviert, ist_neueste), …]}.

    Video    → alle `final_v*.mp4`
    Karussell→ das erste Slide `01_start.png` jedes Versions-Ordners `vN/`
    Auch `veröffentlicht/` wird mitgelesen: ein Ordner, der schon archiviert
    wurde, soll keinen falschen Neu-Eintrag erzeugen, sondern erkannt werden.

    `ist_neueste` markiert die hoechste Version im Ordner. Wichtig: es kommt vor,
    dass eine alte Fassung online gegangen ist und danach weitergearbeitet wurde
    (Video 024: v3 lief am 03.07., dann entstanden v4/v5 und die Freigabe steht
    wieder auf OFFEN). So ein Ordner darf NICHT als „online" eingetragen werden —
    sonst raeumt der Archiv-Lauf ihn weg und loescht dabei die neueren Fassungen.
    """
    base = area_base(area)
    roots = [(base, False), (base / "veröffentlicht", True)]
    by_size: dict[int, list[tuple[Path, Path, bool, bool]]] = {}
    for root, archived in roots:
        if not root.is_dir():
            continue
        for folder in sorted(root.iterdir()):
            if not folder.is_dir() or not re.match(r"^\d{3}_", folder.name):
                continue
            files = (sorted(folder.glob("final_v*.mp4")) if area == "video"
                     else sorted(folder.glob("v*/01_start.png")))
            if not files:
                continue
            newest = max(_version_num(f) for f in files)
            for f in files:
                try:
                    size = f.stat().st_size
                except OSError:
                    continue
                by_size.setdefault(size, []).append(
                    (folder, f, archived, _version_num(f) == newest))
    return by_size


# --------------------------------------------------------------------------- #
# GHL-Media: Grösse per HEAD
# --------------------------------------------------------------------------- #

_size_cache: dict[str, int | None] = {}


def media_size(url: str) -> int | None:
    if url in _size_cache:
        return _size_cache[url]
    size = None
    try:
        r = requests.head(url, timeout=30, allow_redirects=True)
        cl = r.headers.get("Content-Length")
        size = int(cl) if cl else None
    except Exception:
        size = None
    _size_cache[url] = size
    return size


def published_posts(client: GHLClient, days: int) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    out: list[dict] = []
    seen: set[str] = set()
    skip = 0
    while skip < 500:
        posts = client.search_posts(post_status="published", limit=100,
                                    skip=skip, from_date=since)
        if not posts:
            break
        for p in posts:
            pid = str(p.get("_id") or p.get("id") or "")
            if pid and pid not in seen:
                seen.add(pid)
                out.append(p)
        if len(posts) < 100:
            break
        skip += 100
    return out


# --------------------------------------------------------------------------- #
# Abgleich
# --------------------------------------------------------------------------- #

def _base(url: str | None) -> str:
    return (url or "").rsplit("/", 1)[-1]


def _sha_or_none(f: Path) -> str | None:
    """SHA-256, aber nie am Ledger-Abgleich scheitern.

    Die Freigabe-Ordner liegen in OneDrive: nicht heruntergeladene Dateien sind
    Platzhalter, deren Lesen minutenlang haengt oder mit Timeout abbricht. Die
    Groesse liefert `stat()` trotzdem — fuer die Zuordnung reicht sie, der Hash
    ist nur fuer das spaetere Aufraeumen alter Versionen relevant.
    """
    try:
        return sha256_file(f)
    except OSError as e:
        print(f"    (Hash uebersprungen, Datei nicht lokal verfuegbar: {f.name} — {e})")
        return None


def reconcile(ledger: dict, posts: list[dict], areas: list[str]) -> tuple[list, list]:
    """(neue Einträge, korrigierte Einträge) berechnen — ohne zu speichern."""
    cands = {a: local_candidates(a) for a in areas}
    by_key = {}  # (folder, account) -> ledger entry
    for e in ledger.get("entries", []):
        for a in (e.get("account_ids") or []):
            by_key[(e.get("folder"), a)] = e

    added: list[dict] = []
    fixed: list[tuple[dict, str, str]] = []
    skipped: dict[str, str] = {}   # Ordner → online gegangene, aber ueberholte Fassung

    for p in posts:
        media = p.get("media") or []
        if not media:
            continue
        url = media[0].get("url")
        size = media_size(url)
        if not size:
            continue
        hit = None
        for area in areas:
            for folder, f, archived, is_latest in cands[area].get(size, []):
                hit = (area, folder, f, archived, is_latest)
                break
            if hit:
                break
        if not hit:
            continue
        area, folder, f, archived, is_latest = hit
        for acc in (p.get("accountIds") or []):
            e = by_key.get((folder.name, acc))
            m0 = media[0]
            if e is None and archived:
                # Schon archiviert und ohne Ledger-Eintrag: nichts zu retten,
                # der Ordner ist bereits weg aus dem Freigabe-Verzeichnis.
                continue
            if e is None and not is_latest:
                skipped.setdefault(folder.name, f.name)
                continue
            if e is None:
                entry = {
                    "sha256": _sha_or_none(f),
                    "folder": folder.name,
                    "media_name": f.name,
                    "source_path": str(f),
                    "size_bytes": size,
                    "account_ids": [acc],
                    "published_at": p.get("publishedAt"),
                    "post_id": p.get("_id") or p.get("id"),
                    "media_id": m0.get("id") or m0.get("_id"),
                    "media_url": url,
                    "status": "published",
                    "schedule_date": p.get("scheduleDate"),
                    "reauthored_user": p.get("createdBy"),
                }
                ledger.setdefault("entries", []).append(entry)
                by_key[(folder.name, acc)] = entry
                added.append(entry)
            elif _base(e.get("media_url")) != _base(url):
                old = _base(e.get("media_url"))
                e["media_url"] = url
                e["media_id"] = m0.get("id") or m0.get("_id") or e.get("media_id")
                e["post_id"] = p.get("_id") or p.get("id")
                e["status"] = "published"
                e["published_at"] = p.get("publishedAt")
                e["schedule_date"] = p.get("scheduleDate")
                fixed.append((e, old, _base(url)))
            elif e.get("status") != "published":
                e["status"] = "published"
                e["published_at"] = p.get("publishedAt") or e.get("published_at")
                fixed.append((e, e.get("status") or "?", "published"))

    return added, fixed, skipped


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ledger gegen die veröffentlichten GHL-Posts abgleichen")
    ap.add_argument("--area", choices=["video", "carousel", "all"], default="all")
    ap.add_argument("--days", type=int, default=90,
                    help="Wie weit zurück in GHL geschaut wird (Default: 90)")
    ap.add_argument("--execute", action="store_true",
                    help="Ledger wirklich schreiben (sonst Dry-Run)")
    args = ap.parse_args()

    areas = list(AREAS) if args.area == "all" else [args.area]
    client = GHLClient(_load_env_key("GHL_PRIVATE_INTEGRATION_TOKEN"),
                       _load_env_key("GHL_LOCATION_ID"))
    posts = published_posts(client, args.days)
    print(f"{len(posts)} veröffentlichte Posts der letzten {args.days} Tage geprüft.")

    ledger = load_ledger()
    added, fixed, skipped = reconcile(ledger, posts, areas)

    for folder, name in sorted(skipped.items()):
        print(f"  ! UEBERSPRUNGEN {folder[:44]:<46} {name} ist online, "
              f"lokal liegt aber schon eine neuere Fassung — Ordner bleibt liegen.")

    if not added and not fixed:
        print("Ledger ist synchron — nichts nachzutragen.")
        return

    for e in added:
        print(f"  + NEU     {e['folder'][:46]:<48} {e['media_name']:<34} "
              f"{(e['account_ids'] or [''])[0][-24:]}")
    for e, old, new in fixed:
        print(f"  ~ KORREKT {e['folder'][:46]:<48} {old[:20]} → {new[:20]}")

    if args.execute:
        save_ledger(ledger)
        print(f"\nLedger geschrieben: +{len(added)} neu, ~{len(fixed)} korrigiert.")
        print("Nicht vergessen: ghl_publish_log.json ist git-getrackt.")
    else:
        print(f"\nDRY-RUN — mit --execute schreiben (+{len(added)} neu, "
              f"~{len(fixed)} korrigiert).")


if __name__ == "__main__":
    main()
