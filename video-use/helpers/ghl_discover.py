"""Discover GoHighLevel social planner accounts (read-only).

Calls GET /social-media-posting/{locationId}/accounts and prints the connected
social accounts with their ids and platforms. This is the safe first step to
verify that GHL_PRIVATE_INTEGRATION_TOKEN + GHL_LOCATION_ID are correct and to
see the real account-object shapes BEFORE attempting any post.

Usage:
    python helpers/ghl_discover.py            # pretty table
    python helpers/ghl_discover.py --json     # raw JSON dump (inspect true shape)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transcribe import _load_env_key  # noqa: E402
from ghl_client import GHLClient, GHLError  # noqa: E402


def _platform_of(acc: dict) -> str:
    return (
        acc.get("platform")
        or acc.get("type")
        or acc.get("provider")
        or acc.get("oAuthType")
        or "?"
    )


def _name_of(acc: dict) -> str:
    return acc.get("name") or acc.get("displayName") or acc.get("accountName") or ""


def main() -> None:
    ap = argparse.ArgumentParser(description="Discover GHL social planner accounts")
    ap.add_argument("--json", action="store_true", help="Print raw JSON response")
    args = ap.parse_args()

    token = _load_env_key("GHL_PRIVATE_INTEGRATION_TOKEN")
    location_id = _load_env_key("GHL_LOCATION_ID")
    client = GHLClient(token, location_id)

    print(f"querying social planner accounts for location {location_id} …")
    try:
        resp = client.list_accounts()
    except GHLError as e:
        sys.exit(str(e))

    if args.json:
        print(json.dumps(resp, indent=2, ensure_ascii=False))
        return

    # Real shape: {"success": true, "results": {"accounts": [...]}}.
    # Fall back to a few other shapes seen across GHL API versions.
    accounts = None
    if isinstance(resp, dict):
        results = resp.get("results")
        if isinstance(results, dict):
            accounts = results.get("accounts")
        if accounts is None:
            accounts = resp.get("accounts")
    if accounts is None and isinstance(resp, list):
        accounts = resp
    if not accounts:
        print("no connected accounts found. Connect channels in the GHL Social "
              "Planner first, or run with --json to inspect the raw response:")
        print(json.dumps(resp, indent=2, ensure_ascii=False)[:1000])
        return

    print()
    print(f"{'PLATFORM':<12} {'ACCOUNT_ID':<28} {'NAME'}")
    print("-" * 70)
    for acc in accounts:
        acc_id = acc.get("id") or acc.get("_id") or ""
        print(f"{_platform_of(acc):<12} {str(acc_id):<28} {_name_of(acc)}")

    print()
    print(f"{len(accounts)} account(s) connected.")


if __name__ == "__main__":
    main()
