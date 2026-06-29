"""Scheduling slots for GoHighLevel social planner posts.

Convention (anchored 2026-06-29):
    - All posts go out at 10:00 Europe/Berlin (DST-aware).
    - Default cadence days are Monday, Wednesday, Friday.
    - Never two posts on the same day: occupied days are read live from GHL
      (existing `scheduled` + `draft` posts) and skipped, so multiple videos
      automatically spread across the next free Mon/Wed/Fri slots.

The weekday set is parameterizable so future content types can use their own
cycle (e.g. videos Mon/Fri, image posts Wed).

Used as a library (by ghl_push.py) and as a CLI to show what is already planned:

    python helpers/ghl_schedule.py                 # upcoming plan, grouped by week
    python helpers/ghl_schedule.py --weeks 6
    python helpers/ghl_schedule.py --preview 3     # show the next 3 free slots
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transcribe import _load_env_key  # noqa: E402
from ghl_client import GHLClient, GHLError  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")
DEFAULT_HOUR = 10
DEFAULT_MINUTE = 0
DEFAULT_WEEKDAYS = (0, 2, 4)  # Mon, Wed, Fri

WEEKDAY_NAMES = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
WEEKDAY_ALIASES = {
    "mon": 0, "mo": 0, "montag": 0,
    "tue": 1, "di": 1, "dienstag": 1,
    "wed": 2, "mi": 2, "mittwoch": 2,
    "thu": 3, "do": 3, "donnerstag": 3,
    "fri": 4, "fr": 4, "freitag": 4,
    "sat": 5, "sa": 5, "samstag": 5,
    "sun": 6, "so": 6, "sonntag": 6,
}


def parse_weekdays(spec: str | None) -> tuple[int, ...]:
    """Parse 'mon,wed,fri' (or German aliases) into a sorted weekday tuple."""
    if not spec:
        return DEFAULT_WEEKDAYS
    out: list[int] = []
    for tok in spec.replace(";", ",").split(","):
        t = tok.strip().lower()
        if not t:
            continue
        if t not in WEEKDAY_ALIASES:
            raise ValueError(f"unknown weekday: {tok!r}")
        out.append(WEEKDAY_ALIASES[t])
    return tuple(sorted(set(out))) or DEFAULT_WEEKDAYS


def parse_time(spec: str | None) -> tuple[int, int]:
    """Parse 'HH:MM' into (hour, minute)."""
    if not spec:
        return DEFAULT_HOUR, DEFAULT_MINUTE
    hh, _, mm = spec.partition(":")
    return int(hh), int(mm or 0)


def _parse_iso(s: str) -> datetime:
    """Parse a GHL ISO timestamp (handles trailing 'Z')."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def to_ghl_date(dt: datetime) -> str:
    """Serialize a tz-aware datetime to the UTC ISO string GHL expects."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def get_occupied_days(
    client: GHLClient,
    *,
    from_date: datetime,
    to_date: datetime,
    statuses: tuple[str, ...] = ("scheduled", "draft"),
) -> dict:
    """Return {date(Berlin): [post, ...]} for posts that already occupy a day.

    Only posts carrying an explicit scheduleDate within the window count — a
    "save for later" draft without an intended time does not block a day.
    """
    occupied: dict = {}
    for st in statuses:
        try:
            posts = client.search_posts(
                post_status=st, from_date=from_date, to_date=to_date, limit=100
            )
        except GHLError:
            posts = []
        for p in posts:
            raw = p.get("scheduleDate")
            if not raw:
                continue
            day = _parse_iso(raw).astimezone(BERLIN).date()
            occupied.setdefault(day, []).append(p)
    return occupied


def get_account_occupancy(
    client: GHLClient,
    *,
    from_date: datetime,
    to_date: datetime,
    statuses: tuple[str, ...] = ("scheduled", "draft"),
) -> dict:
    """Return {account_id: {slot_datetime(Berlin, minute-precision), ...}}.

    Occupancy is PER ACCOUNT and per time slot: the same time can hold posts on
    several different channels (Instagram + LinkedIn + Facebook at Mon 10:00 is
    fine) — only the SAME account must not be double-booked on a time slot.
    """
    occ: dict = {}
    for st in statuses:
        try:
            posts = client.search_posts(
                post_status=st, from_date=from_date, to_date=to_date, limit=100
            )
        except GHLError:
            posts = []
        for p in posts:
            raw = p.get("scheduleDate")
            if not raw:
                continue
            dt = _parse_iso(raw).astimezone(BERLIN).replace(second=0, microsecond=0)
            for acc in (p.get("accountIds") or []):
                occ.setdefault(acc, set()).add(dt)
    return occ


def compute_slots(
    count: int,
    account_ids: list[str],
    *,
    weekdays: tuple[int, ...] = DEFAULT_WEEKDAYS,
    hour: int = DEFAULT_HOUR,
    minute: int = DEFAULT_MINUTE,
    now: datetime | None = None,
    occupancy: dict | None = None,
    skip_days: set | None = None,
    extra_taken: dict | None = None,
) -> list[datetime]:
    """Compute the next `count` free time slots (tz-aware Berlin datetimes).

    A slot is free for THIS post when none of its target `account_ids` already
    has a post at that exact slot — neither in `occupancy` (live from the API)
    nor in `extra_taken` (assigned earlier in the same run; mutated in place).
    `skip_days` is a blunt manual override: dates to avoid for all accounts.
    Only future slots are returned.
    """
    now = now or datetime.now(BERLIN)
    occupancy = occupancy or {}
    taken = extra_taken if extra_taken is not None else {}
    skip = set(skip_days or ())
    slots: list[datetime] = []
    cur = now.date()
    guard = 0
    while len(slots) < count and guard < 800:
        guard += 1
        if cur.weekday() in weekdays and cur not in skip:
            slot = datetime.combine(cur, time(hour, minute), tzinfo=BERLIN)
            if slot > now:
                conflict = any(
                    slot in occupancy.get(a, ()) or slot in taken.get(a, ())
                    for a in account_ids
                )
                if not conflict:
                    slots.append(slot)
                    for a in account_ids:
                        taken.setdefault(a, set()).add(slot)
        cur += timedelta(days=1)
    return slots


def next_free_slots(
    client: GHLClient,
    count: int,
    account_ids: list[str],
    *,
    weekdays: tuple[int, ...] = DEFAULT_WEEKDAYS,
    hour: int = DEFAULT_HOUR,
    minute: int = DEFAULT_MINUTE,
    skip_days: set | None = None,
    extra_taken: dict | None = None,
) -> list[datetime]:
    """High-level: read per-account occupancy from GHL, then compute free slots."""
    now = datetime.now(BERLIN)
    window_end = now + timedelta(days=400)
    occ = get_account_occupancy(client, from_date=now, to_date=window_end)
    return compute_slots(
        count,
        account_ids,
        weekdays=weekdays,
        hour=hour,
        minute=minute,
        now=now,
        occupancy=occ,
        skip_days=skip_days,
        extra_taken=extra_taken,
    )


# -------- CLI: show the plan ------------------------------------------------


def _platform_label(p: dict) -> str:
    return p.get("platform") or "?"


def main() -> None:
    ap = argparse.ArgumentParser(description="Show / preview GHL social planner scheduling")
    ap.add_argument("--weeks", type=int, default=6,
                    help="How many weeks ahead to show (default 6)")
    ap.add_argument("--preview", type=int, metavar="N",
                    help="Instead of the plan, print the next N free slots")
    ap.add_argument("--weekdays", help="Cadence days, e.g. 'mon,wed,fri' (default)")
    ap.add_argument("--time", dest="time_str", help="Slot time HH:MM (default 10:00)")
    ap.add_argument("--account", action="append", default=[], dest="accounts",
                    help="Account id to consider for --preview occupancy (repeatable). "
                         "Omit for pure cadence slots.")
    args = ap.parse_args()

    weekdays = parse_weekdays(args.weekdays)
    hour, minute = parse_time(args.time_str)

    client = GHLClient(
        _load_env_key("GHL_PRIVATE_INTEGRATION_TOKEN"),
        _load_env_key("GHL_LOCATION_ID"),
    )

    if args.preview:
        slots = next_free_slots(client, args.preview, args.accounts,
                                weekdays=weekdays, hour=hour, minute=minute)
        scope = f" for {len(args.accounts)} account(s)" if args.accounts else " (pure cadence)"
        print(f"next {args.preview} free slot(s){scope} "
              f"({'/'.join(WEEKDAY_NAMES[w] for w in weekdays)} {hour:02d}:{minute:02d} Europe/Berlin):")
        for s in slots:
            print(f"  {WEEKDAY_NAMES[s.weekday()]} {s:%Y-%m-%d %H:%M %Z}")
        return

    now = datetime.now(BERLIN)
    end = now + timedelta(weeks=args.weeks)
    occ = get_occupied_days(client, from_date=now, to_date=end)
    if not occ:
        print(f"nothing scheduled/draft-dated in the next {args.weeks} weeks.")
        return

    print(f"Geplant / als Entwurf datiert (nächste {args.weeks} Wochen, Europe/Berlin):\n")
    last_week = None
    for day in sorted(occ):
        iso_year, iso_week, _ = day.isocalendar()
        if (iso_year, iso_week) != last_week:
            last_week = (iso_year, iso_week)
            print(f"— KW {iso_week} ({iso_year}) —")
        for p in occ[day]:
            dt = _parse_iso(p["scheduleDate"]).astimezone(BERLIN)
            summary = (p.get("summary") or "").replace("\n", " ")[:50]
            print(f"   {WEEKDAY_NAMES[day.weekday()]} {dt:%Y-%m-%d %H:%M}  "
                  f"[{p.get('status'):<9}] {_platform_label(p):<10} {summary}")
    print()


if __name__ == "__main__":
    main()
