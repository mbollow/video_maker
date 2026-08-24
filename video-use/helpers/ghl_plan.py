"""ghl_plan.py — orchestrate GoHighLevel drafts from the Freigabe folders.

Scans the Video + Karussell Freigabe areas, reads each FREIGABE…txt
(STATUS + channel checkboxes), and for every FREIGEGEBEN folder creates
SCHEDULED posts on the *checked* channels, each on that content type's weekday
slot at 09:55 Europe/Berlin — next free day per channel.

Content → weekday matrix (09:55 Europe/Berlin):
    reel (video):  Instagram/Facebook  Mon + Fri   |  LinkedIn  Fri
    carousel:      Instagram/Facebook  Wed         |  LinkedIn  Wed
Single image posts are intentionally NOT scheduled here (yet).

Channel checkboxes (in the FREIGABE header):
    [x] Instagram  -> Instagram + Facebook accounts (both Meta, same caption)
    [x] LinkedIn   -> LinkedIn account (Juliana's personal profile)

Posts gehen direkt scharf raus (status=scheduled): die inhaltliche Pruefung
passiert vorher im Freigabe-Ordner, der Draft-Umweg hat nur Klicks im GHL-UI
gekostet. `--status draft` legt sie stattdessen als Entwurf an. AUSNAHME, die
Das gilt auch fuer Karussells: Die API meldet dort nach dem Terminieren zwar
nur ein Medium, das ist aber ein Lesefehler — veroeffentlicht wird mit allen
Folien (belegt am 19.08.2026, Instagram + LinkedIn).

Nach dem Terminieren wandert jeder erfolgreich eingeplante Freigabe-Ordner
direkt nach `<Bereich>/veroeffentlicht/NNN_slug_<termin>/` — mit dem GEPLANTEN
Termin im Ordnernamen. Grund: der taegliche Archiv-Cron haengt am GHL-Feld
`publishedAt`, das fuer Karussells nie gesetzt wird; deren Ordner blieben
dadurch dauerhaft liegen. `--no-archive` ist der Notausgang, der Cron laeuft
als Netz fuer alles weiter, was hier nicht mitgenommen wurde.

Dedup via den git-getrackten Ledger. DRY-RUN by default — it only prints the
plan. Pass --execute to actually upload media and create the posts.
`--only <text>` beschraenkt den Lauf auf einen bestimmten Freigabe-Ordner.

    npm run ghl:plan:auto                 # dry-run: show the plan
    npm run ghl:plan:auto -- --execute    # create the posts (status=scheduled)

Env (.env): GHL_PRIVATE_INTEGRATION_TOKEN, GHL_LOCATION_ID, GHL_USER_ID
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transcribe import _load_env_key  # noqa: E402
from ghl_client import GHLClient, GHLError  # noqa: E402
from ghl_schedule import (  # noqa: E402
    BERLIN, WEEKDAY_NAMES, compute_slots, get_account_occupancy,
)
from ghl_ledger import (  # noqa: E402
    append_entry, load_ledger, published_accounts_for,
)
from ghl_push import resolve_caption  # noqa: E402
from freigabe_push import DEFAULT_FREIGABE_DIR  # noqa: E402
from ghl_sync_captions import newest_caption_file, sync_video_area  # noqa: E402
from caption_check import check as check_caption  # noqa: E402
from freigabe_archive import archive_folder  # noqa: E402

SLOT_HOUR, SLOT_MIN = 9, 55

# (content_type, platform) -> weekday tuple (0=Mon … 6=Sun).
WEEKDAYS = {
    ("reel", "instagram"): (0, 4),   # Mon + Fri
    ("reel", "facebook"): (0, 4),
    ("reel", "linkedin"): (4,),      # Fri
    ("carousel", "instagram"): (2,),  # Wed
    ("carousel", "facebook"): (2,),
    ("carousel", "linkedin"): (2,),
}

# content type -> Bereich in freigabe_archive (dort heisst 'reel' -> 'video')
ARCHIVE_AREA = {"reel": "video", "carousel": "carousel"}

# checkbox label -> platforms it enables (Instagram checkbox drives both Meta nets)
CHECKBOX_PLATFORMS = {
    "instagram": ("instagram", "facebook"),
    "linkedin": ("linkedin",),
}

SM_BASE = Path(DEFAULT_FREIGABE_DIR).parent  # …/Social_Media_Prototyp
AREAS = [
    # (freigabe subfolder, content_type)
    ("Freigabeprozess – Video", "reel"),
    ("Freigabeprozess – Karussell", "carousel"),
]


# ---------------------------------------------------------------- parsing ----

def parse_freigabe(path: Path) -> tuple[str, set[str]]:
    """Return (STATUS, {checked channel labels}) from a FREIGABE…txt."""
    status = "OFFEN"
    channels: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        m = re.match(r"STATUS\s*:\s*([A-Za-zÄÖÜäöü]+)", s)
        if m:
            status = m.group(1).upper()
            continue
        cm = re.match(r"\[([ xX])\]\s*(Instagram|LinkedIn)\b", s, re.I)
        if cm and cm.group(1).lower() == "x":
            channels.add(cm.group(2).lower())
    return status, channels


def newest_video(folder: Path) -> Path | None:
    vids = list(folder.glob("final_v*.mp4"))
    if not vids:
        return None
    return max(vids, key=lambda p: int(re.search(r"final_v(\d+)", p.name).group(1)))


def newest_carousel_slides(folder: Path) -> list[Path]:
    """Newest version subfolder's slides, in slide order (01_… … 99_ende)."""
    vdirs = [d for d in folder.iterdir() if d.is_dir() and re.fullmatch(r"v\d+", d.name)]
    if not vdirs:
        return []
    newest = max(vdirs, key=lambda d: int(d.name[1:]))
    return sorted(newest.glob("*.png"), key=lambda p: p.name)


def caption_file(folder: Path) -> Path | None:
    # NEWEST captions version (captions_v3 beats captions_v2 beats captions__).
    return newest_caption_file(folder)


def sha_of_files(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------- planning ---

def collect_items(area_dir: Path, content_type: str) -> list[dict]:
    """Return one dict per FREIGEGEBEN folder with checked channels + media."""
    items: list[dict] = []
    if not area_dir.exists():
        return items
    for folder in sorted(p for p in area_dir.iterdir() if p.is_dir()):
        fr = next(iter(folder.glob("FREIGABE*.txt")), None)
        if not fr:
            continue
        status, channels = parse_freigabe(fr)
        if status != "FREIGEGEBEN":
            continue
        if not channels:
            print(f"  [skip] {folder.name}: FREIGEGEBEN, aber KEIN Kanal angehakt")
            continue
        if content_type == "reel":
            media = [newest_video(folder)] if newest_video(folder) else []
            mime = "video/mp4"
        else:
            media = newest_carousel_slides(folder)
            mime = "image/png"
        media = [m for m in media if m]
        if not media:
            print(f"  [skip] {folder.name}: kein Medium gefunden")
            continue
        cap = caption_file(folder)
        if not cap:
            print(f"  [skip] {folder.name}: keine captions…txt")
            continue
        items.append({
            "folder": folder,
            "name": folder.name,
            "content_type": content_type,
            "channels": channels,
            "media": media,
            "mime": mime,
            "caption_raw": cap.read_text(encoding="utf-8"),
            "sha": sha_of_files(media),
        })
    return items


def resolve_targets(item: dict, platform_map: dict) -> list[dict]:
    """Expand checked channels -> concrete {account_id, platform} targets."""
    wanted: set[str] = set()
    for chk in item["channels"]:
        wanted.update(CHECKBOX_PLATFORMS.get(chk, ()))
    targets = []
    for acc, plat in platform_map.items():
        if plat not in wanted:
            continue
        # LinkedIn: NUR Julianas persönliches Profil, NIE die Palstek Company Page.
        if plat == "linkedin" and acc.lower().endswith("_page"):
            continue
        targets.append({"account_id": acc, "platform": plat})
    return targets


def post_type_for(content_type: str, platform: str) -> str:
    if content_type == "reel" and platform == "instagram":
        return "reel"
    return "post"


# ------------------------------------------------------------- archivieren ---

def archive_done(outcome: dict, args) -> None:
    """Terminierte Ordner direkt nach veroeffentlicht/ verschieben.

    Warum sofort und nicht erst wenn der Post wirklich live ist: der taegliche
    Archiv-Cron prueft `publishedAt` — das meldet GHL fuer Karussells NIE
    (derselbe API-Lesefehler wie bei den Mehrbild-Folien), ihre Ordner blieben
    deshalb dauerhaft liegen. Ab hier wandert jeder Ordner mit, sobald seine
    Posts stehen; der Ordnername traegt den GEPLANTEN Termin.

    Uebersprungen wird ein Ordner, wenn ein Kanal fehlgeschlagen ist (er bleibt
    liegen, damit der Rest nachgezogen werden kann) oder bei --status draft
    (Drafts gehen nicht automatisch live).
    """
    if args.no_archive or not outcome:
        return
    if args.status != "scheduled":
        print("\n[archiv] uebersprungen — Drafts gehen nicht automatisch live.")
        return

    todo = [o for o in outcome.values() if o["ok"] and not o["fail"]]
    haenger = [o for o in outcome.values() if o["fail"]]
    if not todo and not haenger:
        return

    print("\nArchivieren → veröffentlicht/ (Ordnername = geplanter Termin):")
    for o in haenger:
        print(f"  [skip] {o['item']['name']}: nicht alle Kanäle durch — Ordner "
              f"bleibt liegen")
    for o in todo:
        item = o["item"]
        area = ARCHIVE_AREA.get(item["content_type"])
        if not area:
            continue
        # Ein klemmender Ordner darf die anderen nicht mitreissen — die Posts
        # stehen zu diesem Zeitpunkt bereits, das Archivieren ist Kosmetik.
        try:
            res = archive_folder(
                item["folder"], area,
                # Gleiche Form wie der Ledger-Eintrag unten: ueber (Dateiname,
                # Groesse) findet prune_video die Endfassung, ohne ein Byte zu
                # lesen — bei OneDrive-Platzhaltern liefe das in einen Timeout.
                published={
                    "shas": {item["sha"]},
                    "files": {(item["media"][0].name,
                               sum(m.stat().st_size for m in item["media"]))},
                },
                pub_dt=o["slot"], execute=True,
            )
        except Exception as e:
            print(f"  [fehler] {item['name']}: {e}")
            continue
        if res.get("error"):
            print(f"  [fehler] {item['name']}: {res['error']}")
            continue
        print(f"  ✓ {item['name']} → veröffentlicht/{Path(res['moved_to']).name}")
        print(f"      behalten: {', '.join(res.get('kept', [])) or '(nichts)'}"
              f"   gelöscht: {', '.join(res.get('deleted', [])) or '(nichts)'}")


# ---------------------------------------------------------------- run --------

def main() -> None:
    ap = argparse.ArgumentParser(description="Plan + draft GHL posts from the Freigabe folders")
    ap.add_argument("--area", choices=["video", "carousel", "all"], default="all")
    ap.add_argument("--only", help="Nur Freigabe-Ordner, deren Name diesen Text enthaelt "
                                   "(z.B. '002_') — sonst laeuft es ueber alle FREIGEGEBEN-Ordner")
    ap.add_argument("--execute", action="store_true",
                    help="Actually upload media + create the drafts (default: dry-run plan)")
    ap.add_argument("--force", action="store_true",
                    help="Ignore the dedup ledger (re-post to accounts already done)")
    ap.add_argument("--captions-ok", action="store_true",
                    help="Bestaetigt, dass die Caption-Fundstellen mit dem Nutzer geklaert sind. "
                         "Ohne das bricht --execute ab, sobald die Vorpruefung etwas findet.")
    ap.add_argument("--status", choices=["draft", "scheduled"], default="scheduled",
                    help="Lifecycle der angelegten Posts. Default 'scheduled' — die Pruefung "
                         "passiert vorab im Freigabe-Ordner. 'draft' legt Entwuerfe an. "
                         "Gilt auch fuer Karussells (der alte Draft-Zwang ist seit "
                         "19.08.2026 weg — die API las nur falsch).")
    ap.add_argument("--no-archive", action="store_true",
                    help="Freigabe-Ordner NICHT nach veroeffentlicht/ verschieben "
                         "(Notausgang; normal wandert jeder terminierte Ordner mit)")
    args = ap.parse_args()

    sel = {"video": ["Freigabeprozess – Video"], "carousel": ["Freigabeprozess – Karussell"]}
    areas = AREAS if args.area == "all" else [
        a for a in AREAS if a[0] in sel[args.area]
    ]

    client = GHLClient(
        _load_env_key("GHL_PRIVATE_INTEGRATION_TOKEN"),
        _load_env_key("GHL_LOCATION_ID"),
    )
    platform_map = client.account_platform_map()
    print("Verbundene Konten (Plattform → Konto):")
    for acc, plat in platform_map.items():
        print(f"   {plat:<10} {acc}")
    print()

    # PFLICHT vor jedem Upload: die handgepflegten captions.txt sind die Wahrheit —
    # ins Manifest spiegeln, bevor irgendetwas zu GHL geht. Blockiert den Push nie.
    try:
        sync_video_area(SM_BASE / "Freigabeprozess – Video")
    except Exception as e:
        print(f"[ghl-sync] Warnung: Caption-Sync übersprungen ({e})")
    print()

    # Gather all FREIGEGEBEN items across the selected areas.
    items: list[dict] = []
    for sub, ctype in areas:
        items += collect_items(SM_BASE / sub, ctype)

    if args.only:
        items = [i for i in items if args.only.lower() in i["name"].lower()]

    if not items:
        print("Nichts zu planen — kein FREIGEGEBEN-Ordner mit angehaktem Kanal gefunden.")
        return

    # Live occupancy (per account, per slot) — so we only put posts on free days.
    now = datetime.now(BERLIN)
    occ = get_account_occupancy(client, from_date=now, to_date=now + timedelta(days=400))
    taken: dict = {}
    ledger = load_ledger()

    print(f"{'STATUS':<8}{'CONTENT':<9}{'KANAL':<10}{'SLOT':<20}ORDNER")
    plan: list[dict] = []
    for item in items:
        targets = resolve_targets(item, platform_map)
        if not targets:
            print(f"  [warn] {item['name']}: angehakte Kanäle {item['channels']} — "
                  f"kein passendes Konto verbunden")
            continue
        already = published_accounts_for(ledger, item["sha"]) if not args.force else set()
        for t in targets:
            plat = t["platform"]
            if t["account_id"] in already:
                print(f"{'SKIP':<8}{item['content_type']:<9}{plat:<10}{'(schon gepostet)':<20}{item['name']}")
                continue
            wds = WEEKDAYS.get((item["content_type"], plat))
            if not wds:
                continue
            slot = compute_slots(1, [t["account_id"]], weekdays=wds,
                                 hour=SLOT_HOUR, minute=SLOT_MIN, now=now,
                                 occupancy=occ, extra_taken=taken)
            if not slot:
                print(f"  [warn] {item['name']}/{plat}: kein freier Slot gefunden")
                continue
            slot = slot[0]
            plan.append({**t, "item": item, "slot": slot})
            tag = "PLAN" if args.execute else "DRY"
            hint = ""
            print(f"{tag:<8}{item['content_type']:<9}{plat:<10}"
                  f"{WEEKDAY_NAMES[slot.weekday()]+' '+slot.strftime('%Y-%m-%d %H:%M'):<20}"
                  f"{item['name']}{hint}")

    print(f"\n{len(plan)} {args.status}-Post(s) geplant "
          f"({'AUSFÜHREN' if args.execute else 'DRY-RUN — nichts gesendet, --execute zum Anlegen'}).")

    # Caption-Vorpruefung: erst pruefen, Fundstellen mit dem Nutzer klaeren, dann
    # hochladen. Ein einmal hochgeladener Tippfehler ist teuer — siehe Karussell 002.
    befunde = {}
    for item in {id(p["item"]): p["item"] for p in plan}.values():
        f = check_caption(item["caption_raw"])
        if f:
            befunde[item["name"]] = f
    if befunde:
        print("\nCAPTION-VORPRUEFUNG — bitte erst klaeren:")
        for name, f in befunde.items():
            print(f"  {name}")
            for x in f:
                print(f"     • {x}")
        print("  (Sinn- und Sachfehler sieht das nicht — zusaetzlich selbst gegenlesen.)")

    if not args.execute or not plan:
        return
    if befunde and not args.captions_ok:
        print("\nABBRUCH: Es ist nichts hochgeladen worden. Fundstellen mit dem Nutzer "
              "klaeren, Captions ggf. korrigieren, danach mit --captions-ok erneut starten.")
        return

    # --- execute: upload media once per item, then create a draft per target ---
    user_id = _load_env_key("GHL_USER_ID")
    media_cache: dict = {}  # item sha -> list[media_entry]
    # Pro Ordner mitschreiben, was geklappt hat — daraus entscheidet sich unten,
    # ob er nach veroeffentlicht/ wandert und mit welchem Datum.
    outcome: dict = {}
    for p in plan:
        item = p["item"]
        if item["sha"] not in media_cache:
            entries = []
            print(f"\nupload media: {item['name']} ({len(item['media'])} Datei(en)) …")
            for m in item["media"]:
                up = client.upload_media(m, file_name=f"{item['name']}__{m.name}",
                                         mime=item["mime"])
                if not up.get("url"):
                    print(f"  ✗ Upload ohne URL: {m.name}")
                    continue
                e = {"url": up["url"], "type": item["mime"]}
                if up.get("id"):
                    e["id"] = up["id"]
                entries.append(e)
            media_cache[item["sha"]] = entries
        oc = outcome.setdefault(item["sha"], {"item": item, "ok": 0, "fail": 0,
                                              "slot": None})
        entries = media_cache[item["sha"]]
        if not entries:
            print(f"  ✗ {item['name']}: kein Medium hochgeladen — übersprungen")
            oc["fail"] += 1
            continue
        caption = resolve_caption(item["caption_raw"], p["platform"], None)
        # Frueher gingen Mehrbild-Posts hier zwangsweise als Draft raus, weil die
        # API nach dem Terminieren nur noch ein Medium meldet. Am 19.08.2026 hat
        # sich das als reiner LESEFEHLER der API erwiesen: Das Karussell wurde
        # auf Instagram und LinkedIn mit allen Folien in richtiger Reihenfolge
        # veroeffentlicht. Der Zwang ist damit weg — Karussells laufen wie alles
        # andere. Details: docs/ghl-karussell-mehrbild.md
        status = args.status
        print(f"creating {status}: {p['platform']} @ {p['slot']:%a %Y-%m-%d %H:%M} — {item['name']}")
        try:
            resp = client.create_post(
                account_ids=[p["account_id"]],
                summary=caption,
                user_id=user_id,
                media=entries,
                status=status,
                post_type=post_type_for(item["content_type"], p["platform"]),
                schedule_date=p["slot"],
            )
        except GHLError as e:
            print(f"  ✗ failed: {e}")
            oc["fail"] += 1
            continue
        post_id = None
        if isinstance(resp, dict):
            res = resp.get("results") if isinstance(resp.get("results"), dict) else resp
            if isinstance(res, dict):
                post = res.get("post") if isinstance(res.get("post"), dict) else res
                post_id = post.get("id") or post.get("_id")
        append_entry(
            ledger, sha=item["sha"], folder=item["name"],
            media_name=item["media"][0].name, source_path=str(item["media"][0]),
            size_bytes=sum(m.stat().st_size for m in item["media"]),
            account_ids=[p["account_id"]],
            published_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            post_id=post_id, media_id=(entries[0].get("id")),
            media_url=entries[0].get("url"), status=status,
            schedule_date=p["slot"].isoformat(),
        )
        print(f"  ✓ {status} angelegt (post_id={post_id})")
        oc["ok"] += 1
        # Frühester Termin des Ordners = sein Veröffentlichungsdatum im Archiv.
        if oc["slot"] is None or p["slot"] < oc["slot"]:
            oc["slot"] = p["slot"]

    archive_done(outcome, args)

    if args.status == "draft":
        print("\nFertig. Alle Posts sind DRAFTS im GHL Social Planner — nichts ist live.")
    else:
        print("\nFertig. Alle Posts stehen als SCHEDULED und gehen zum Termin automatisch raus.")


if __name__ == "__main__":
    main()
