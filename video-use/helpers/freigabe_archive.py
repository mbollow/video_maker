#!/usr/bin/env python3
"""freigabe_archive.py — veröffentlichte Posts nach /veröffentlicht verschieben + aufräumen.

Deckt ZWEI Bereiche ab (analog):
  video    — Freigabeprozess – Video     (final_v*.mp4 + cover*.png)
  carousel — Freigabeprozess – Karussell (Versions-Unterordner v1/ v2/ …)

Ein Post gilt als ONLINE, wenn seine GHL-Posts (aus dem Ledger, per Media+Account
live abgefragt) `publishedAt` gesetzt haben. ERST DANN wird der Freigabe-Ordner
`NNN_slug/` nach `…/<Bereich>/veröffentlicht/NNN_slug_<yyyy-mm-dd>/` verschoben —
das angehängte Datum ist das echte GHL-Veröffentlichungsdatum (Europe/Berlin).

Beim Verschieben werden die historischen Versionen aufgeräumt:
  video    BEHALTEN: online gegangene Endfassung (final_v* mit passendem Ledger-SHA,
                     sonst neueste), neuestes cover*.png, ALLE captions*.txt,
                     FREIGABE*.txt, ANTWORT*.txt, .meta.json, Original-Kameradatei.
           LÖSCHEN : ältere final_v* und ältere cover_v*.
  carousel BEHALTEN: neuester Versions-Ordner vN/, alle captions*/FREIGABE*/ANTWORT*
                     /.meta.json.
           LÖSCHEN : ältere Versions-Ordner v1/ … v(N-1)/.

Default = DRY-RUN (zeigt nur an). Mit --execute wird verschoben/gelöscht.

    python freigabe_archive.py                          # DRY-RUN alle Bereiche
    python freigabe_archive.py --area carousel          # DRY-RUN nur Karussell
    python freigabe_archive.py --execute                # online-Ordner verschieben
    python freigabe_archive.py --folder 001 --area carousel --execute  # forcieren
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ghl_ledger import load_ledger, sha256_file  # noqa: E402
from transcribe import _load_env_key  # noqa: E402
from ghl_client import GHLClient, GHLError  # noqa: E402
import karussell_common as kc  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    _BERLIN = ZoneInfo("Europe/Berlin")
except Exception:  # pragma: no cover
    _BERLIN = None

# Alle Freigabe-Pfade werden aus .env abgeleitet (NIE hartkodieren — die OneDrive-
# Mounts werden umbenannt, siehe Memory „OneDrive-Mount-Rename → .env").
_STALE_DEFAULT_VIDEO = (
    "/Users/marc/Library/CloudStorage/OneDrive-FreigegebeneBibliotheken–PalstekGmbH/"
    "Palstek GmbH - Gäste - General/Social_Media_Prototyp/Freigabeprozess – Video"
)


def _carousel_base() -> Path:
    return Path(kc.freigabe_dir())


def _video_base() -> Path:
    """Video-Freigabe-Ordner: FREIGABE_VIDEO_DIR, sonst aus dem Karussell-Parent
    abgeleitet (gleiches Social_Media_Prototyp/), sonst der (veraltete) Default."""
    env = kc._optional_env("FREIGABE_VIDEO_DIR")
    if env:
        return Path(env)
    try:
        return _carousel_base().parent / "Freigabeprozess – Video"
    except Exception:
        return Path(_STALE_DEFAULT_VIDEO)


def area_base(area: str) -> Path:
    return _carousel_base() if area == "carousel" else _video_base()


AREAS = ("video", "carousel")


# --------------------------------------------------------------------------- #
# Datum / Zeit
# --------------------------------------------------------------------------- #

def _parse_dt(v) -> datetime | None:
    """GHL publishedAt → aware datetime. Akzeptiert ISO-String oder Epoch-ms."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000, tz=timezone.utc)
    s = str(v).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _berlin_date(dt: datetime) -> str:
    """yyyy-mm-dd in Europe/Berlin (Fallback: UTC-Datum)."""
    try:
        local = dt.astimezone(_BERLIN) if _BERLIN else dt.astimezone(timezone.utc)
    except Exception:
        local = dt
    return local.strftime("%Y-%m-%d")


def _today_berlin() -> str:
    now = datetime.now(timezone.utc)
    return _berlin_date(now)


# --------------------------------------------------------------------------- #
# GHL: was ist wirklich online (+ seit wann)
# --------------------------------------------------------------------------- #

def _final_num(p: Path) -> int:
    m = re.search(r"final_v(\d+)", p.name)
    return int(m.group(1)) if m else -1


def _media_base(url: str | None) -> str:
    return (url or "").rsplit("/", 1)[-1]


def published_index(client: GHLClient) -> dict[tuple[str, str], datetime]:
    """{(media_basename, account_id): frühestes publishedAt} über alle veröffentlichten Posts.

    Robust gegen den GHL-Freigabe-Flow: beim Freigeben/Neu-Schedulen eines Drafts
    entstehen neue post_ids (die alten werden deleted), aber die hochgeladene
    Media-Datei (url) bleibt gleich. Daher matchen wir über Media + Account,
    NICHT über die (evtl. veraltete) post_id aus dem Ledger.
    """
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(days=120)  # deckt viele Wochen Cadence ab
    idx: dict[tuple[str, str], datetime] = {}
    skip = 0
    while skip < 500:
        posts = client.search_posts(post_status="published", limit=100, skip=skip,
                                    from_date=since)
        if not posts:
            break
        for p in posts:
            dt = _parse_dt(p.get("publishedAt"))
            if dt is None:
                continue
            bases = {_media_base(m.get("url")) for m in (p.get("media") or [])}
            for a in (p.get("accountIds") or []):
                for b in bases:
                    if not b:
                        continue
                    key = (b, a)
                    if key not in idx or dt < idx[key]:
                        idx[key] = dt  # frühestes Live-Datum gewinnt
        if len(posts) < 100:
            break
        skip += 100
    return idx


def _entry_area(entries: list[dict]) -> str | None:
    """Bereich eines Freigabe-Ordners aus den source_path der Ledger-Einträge ableiten."""
    for e in entries:
        sp = e.get("source_path") or ""
        if "Karussell" in sp:
            return "carousel"
        if "Video" in sp:
            return "video"
    return None


def folder_states(ledger: dict, idx: dict[tuple[str, str], datetime]) -> dict:
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
        live_dts = [idx[pr] for pr in live if pr in idx]
        pub_dt = min(live_dts) if live_dts else None
        out[folder] = {
            "entries": ents,
            "area": _entry_area(ents),
            "online": online,
            "n_live": len(live),
            "n_total": len(pairs),
            "shas": {e.get("sha256") for e in ents if e.get("sha256")},
            "pub_dt": pub_dt,
        }
    return out


# --------------------------------------------------------------------------- #
# Prune pro Bereich
# --------------------------------------------------------------------------- #

def prune_video(folder: Path, published_shas: set[str], execute: bool) -> dict:
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
    return {
        "kept": sorted(p.name for p in (keep_finals | keep_covers)),
        "deleted": sorted(p.name for p in to_delete),
    }


def prune_carousel(folder: Path, published_shas: set[str], execute: bool) -> dict:
    """Nur den neuesten Versions-Ordner vN/ behalten, ältere Versionen löschen."""
    vdirs = sorted(
        [d for d in folder.iterdir() if d.is_dir() and re.fullmatch(r"v\d+", d.name)],
        key=lambda p: int(p.name[1:]),
    )
    keep = {vdirs[-1]} if vdirs else set()
    to_delete = [d for d in vdirs if d not in keep]
    for d in to_delete:
        if execute:
            shutil.rmtree(d)
    return {
        "kept": sorted(p.name for p in keep),
        "deleted": sorted(p.name for p in to_delete),
    }


PRUNE = {"video": prune_video, "carousel": prune_carousel}


def archive_folder(folder: Path, area: str, published_shas: set[str],
                   pub_dt: datetime | None, execute: bool) -> dict:
    res = PRUNE[area](folder, published_shas, execute)
    date_tag = _berlin_date(pub_dt) if pub_dt else _today_berlin()
    archive = area_base(area) / "veröffentlicht"
    dst = archive / f"{folder.name}_{date_tag}"
    if execute:
        archive.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            res["error"] = f"Zielordner existiert schon: {dst}"
            return res
        shutil.move(str(folder), str(dst))
    res["moved_to"] = str(dst)
    res["date"] = date_tag
    return res


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _make_client() -> GHLClient:
    return GHLClient(_load_env_key("GHL_PRIVATE_INTEGRATION_TOKEN"),
                     _load_env_key("GHL_LOCATION_ID"))


def _find_folder_area(number: str, want_area: str | None) -> tuple[Path, str]:
    """Ordner NNN_* in den (gewünschten) Bereichen suchen; Bereich eindeutig bestimmen."""
    areas = [want_area] if want_area else list(AREAS)
    hits: list[tuple[Path, str]] = []
    for a in areas:
        base = area_base(a)
        if not base.exists():
            continue
        for p in base.iterdir():
            if p.is_dir() and re.match(rf"^{number}_", p.name):
                hits.append((p, a))
    if not hits:
        where = want_area or "Video/Karussell"
        sys.exit(f"Kein Ordner {number}_* in Bereich {where} gefunden.")
    if len(hits) > 1:
        sys.exit(f"Ordner {number}_* existiert in mehreren Bereichen "
                 f"({', '.join(a for _, a in hits)}). Bitte --area setzen.")
    return hits[0]


def main() -> None:
    ap = argparse.ArgumentParser(description="Veröffentlichte Posts archivieren + aufräumen")
    ap.add_argument("--area", choices=["video", "carousel", "all"], default="all",
                    help="Bereich (Default: all = Video + Karussell)")
    ap.add_argument("--execute", action="store_true",
                    help="Wirklich verschieben/löschen (sonst Dry-Run)")
    ap.add_argument("--folder", help="Bestimmten Ordner NNN forcieren (ohne Online-Check)")
    args = ap.parse_args()

    want_area = None if args.area == "all" else args.area
    ledger = load_ledger()

    # --- Force-Modus: einen Ordner ohne Online-Check archivieren ---
    if args.folder:
        folder, area = _find_folder_area(args.folder, want_area)
        shas = {e.get("sha256") for e in ledger.get("entries", [])
                if e.get("folder") == folder.name}
        # Echtes Live-Datum best-effort aus GHL holen (sonst heute).
        pub_dt = None
        try:
            idx = published_index(_make_client())
            st = folder_states(ledger, idx).get(folder.name)
            pub_dt = st["pub_dt"] if st else None
        except (GHLError, Exception):
            pub_dt = None
        res = archive_folder(folder, area, shas, pub_dt, args.execute)
        tag = "VERSCHOBEN" if args.execute else "DRY-RUN"
        print(f"[{args.folder}/{area}] {tag} → {area}/veröffentlicht/{Path(res['moved_to']).name}")
        print(f"    behalten: {', '.join(res.get('kept', [])) or '(nichts)'}")
        print(f"    gelöscht: {', '.join(res.get('deleted', [])) or '(nichts)'}")
        if res.get("error"):
            print(f"    FEHLER: {res['error']}")
        return

    # --- Auto-Modus: online-Status live prüfen ---
    idx = published_index(_make_client())
    states = folder_states(ledger, idx)
    if not states:
        print("Keine Posts im Ledger."); return

    # Bereichs-Filter anwenden
    areas = [want_area] if want_area else list(AREAS)
    states = {f: s for f, s in states.items() if s["area"] in areas}
    if not states:
        print(f"Keine Posts im Bereich {args.area}."); return

    print(f"{'Ordner':<52}{'Bereich':<11}{'live/gesamt':<13}{'online?'}")
    print("-" * 84)
    online = []
    for folder, s in sorted(states.items()):
        area = s["area"]
        base = area_base(area) if area else None
        present = bool(base and (base / folder).is_dir())
        note = "" if present else "  (schon archiviert / verschoben)"
        live = f"{s['n_live']}/{s['n_total']}"
        date = _berlin_date(s["pub_dt"]) if s["pub_dt"] else "—"
        print(f"{folder[:50]:<52}{(area or '?'):<11}{live:<13}"
              f"{('JA ' + date) if s['online'] else 'nein'}{note}")
        if s["online"] and present and area:
            online.append((folder, s))

    if not online:
        print("\nNichts zu archivieren (kein Post vollständig online)."); return

    print(f"\n{'AUSFÜHREN' if args.execute else 'DRY-RUN — mit --execute wirklich verschieben'}:")
    fehler = 0
    for folder, s in online:
        area = s["area"]
        # Ein Ordner, der klemmt, darf die anderen NICHT mitreissen: der Lauf ist
        # unbeaufsichtigt (LaunchAgent). Ein PermissionError auf einem Karussell
        # hat hier schon drei Tage lang verhindert, dass ein laengst veroeffentlichtes
        # Video wegarchiviert wurde.
        try:
            res = archive_folder(area_base(area) / folder, area, s["shas"],
                                 s["pub_dt"], args.execute)
        except Exception as e:
            fehler += 1
            print(f"  [{folder[:3]}/{area}] FEHLER, uebersprungen: {e}")
            continue
        tag = "verschoben" if args.execute else "würde verschieben"
        print(f"  [{folder[:3]}/{area}] {tag} → veröffentlicht/{Path(res['moved_to']).name}")
        print(f"       behalten: {', '.join(res.get('kept', [])) or '(nichts)'}")
        print(f"       löschen : {', '.join(res.get('deleted', [])) or '(nichts)'}")
        if res.get("error"):
            fehler += 1
            print(f"       FEHLER: {res['error']}")

    if fehler:
        print(f"\n{fehler} Ordner mit Fehlern — der Rest wurde verarbeitet.")
        sys.exit(1)


if __name__ == "__main__":
    main()
