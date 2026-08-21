"""Zeigt Status + Medienzahl der GHL-Posts eines Freigabe-Ordners.

ACHTUNG, sonst laeuft man in einen Fehlalarm: Bei TERMINIERTEN Mehrbild-Posts
meldet die GHL-API nur ein Medium, obwohl alle Folien vorhanden sind und
vollstaendig veroeffentlicht werden (belegt am 19.08.2026 auf Instagram und
LinkedIn, siehe docs/ghl-karussell-mehrbild.md). Die Zahl ist dort also nicht
aussagekraeftig - --expect schlaegt bei solchen Posts deshalb NICHT an.

Nuetzlich bleibt der Helfer fuer Drafts, fuer Einzelmedien und um Termin und
Status auf einen Blick zu sehen.

    npm run ghl:check-media                    # alle Posts aus dem Ledger
    npm run ghl:check-media -- --only 003      # nur ein Freigabe-Ordner
    npm run ghl:check-media -- --expect 6      # Warnung, wenn weniger Folien

Exit-Code 1, sobald ein Post weniger Medien hat als erwartet — so faellt es auch
in einem Skript auf.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transcribe import _load_env_key  # noqa: E402
from ghl_client import GHLClient, GHLError  # noqa: E402
from ghl_ledger import load_ledger  # noqa: E402


def unwrap(resp: dict) -> dict:
    r = resp.get("results") if isinstance(resp.get("results"), dict) else resp
    return r.get("post") if isinstance(r.get("post"), dict) else r


def ledger_rows(ledger) -> list[dict]:
    rows = ledger.get("entries") if isinstance(ledger, dict) else ledger
    return [r for r in (rows or []) if r.get("post_id")]


def main() -> None:
    ap = argparse.ArgumentParser(description="Status + Medienzahl der GHL-Posts pruefen")
    ap.add_argument("--only", help="Nur Eintraege, deren Ordnername diesen Text enthaelt")
    ap.add_argument("--expect", type=int, help="Erwartete Medienzahl (sonst nur Anzeige)")
    args = ap.parse_args()

    client = GHLClient(
        _load_env_key("GHL_PRIVATE_INTEGRATION_TOKEN"),
        _load_env_key("GHL_LOCATION_ID"),
    )
    rows = ledger_rows(load_ledger())
    if args.only:
        rows = [r for r in rows if args.only.lower() in (r.get("folder") or "").lower()]
    if not rows:
        print("Keine passenden Ledger-Eintraege.")
        return

    problems = 0
    print(f"{'STATUS':<11}{'FOLIEN':<8}{'TERMIN':<18}ORDNER")
    for r in rows:
        try:
            p = unwrap(client.get_post(r["post_id"]))
        except GHLError as e:
            print(f"{'FEHLER':<11}{'?':<8}{'':<18}{r.get('folder')} ({str(e)[:60]})")
            problems += 1
            continue
        if p.get("deleted"):
            continue
        n = len(p.get("media") or [])
        sched = (p.get("scheduleDate") or "")[:16].replace("T", " ")
        flag = ""
        status = p.get("status", "")
        # Terminierte Mehrbild-Posts: Die API meldet 1, obwohl alle Folien da
        # sind. Kein Alarm - sonst schlaegt das Werkzeug bei jedem Karussell an
        # und wird nach zwei Wochen ignoriert.
        api_unzuverlaessig = status == "scheduled" and args.expect and args.expect > 1
        if api_unzuverlaessig:
            flag = "  (terminierter Mehrbild-Post: API-Zahl unzuverlaessig, siehe Doku)"
        elif args.expect and n < args.expect:
            flag = f"  <- nur {n} statt {args.expect}: Folien gekappt, Post neu anlegen"
            problems += 1
        print(f"{p.get('status',''):<11}{n:<8}{sched:<18}{r.get('folder')}{flag}")

    if problems:
        print(f"\n{problems} Post(s) auffaellig. Gekappte Posts lassen sich NICHT per Update "
              f"reparieren — loeschen und neu anlegen.")
        sys.exit(1)
    print("\nAlles unauffaellig.")


if __name__ == "__main__":
    main()
