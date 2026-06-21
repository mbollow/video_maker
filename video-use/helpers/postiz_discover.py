"""Discover Postiz integration IDs via the Public API.

Calls GET /public/v1/integrations and prints a ready-to-paste block of
POSTIZ_<PLATFORM>_INTEGRATION_ID=... lines for `.env`. Optionally writes
them directly to .env (with --write).

Useful after each new OAuth-connected platform in Postiz UI — instead of
manually copying IDs.

Usage:
    python helpers/postiz_discover.py                 # print to stdout
    python helpers/postiz_discover.py --write         # auto-update .env
    python helpers/postiz_discover.py --json          # raw JSON dump
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transcribe import _load_env_key  # noqa: E402
from postiz_client import PostizClient, PostizError  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

ENV_KEY_PER_PLATFORM = {
    "linkedin":  "POSTIZ_LINKEDIN_INTEGRATION_ID",
    "instagram": "POSTIZ_INSTAGRAM_INTEGRATION_ID",
    "tiktok":    "POSTIZ_TIKTOK_INTEGRATION_ID",
    "youtube":   "POSTIZ_YOUTUBE_INTEGRATION_ID",
}


def normalize_platform(provider_or_name: str) -> str | None:
    """Map a Postiz provider/identifier to one of our 4 supported platforms."""
    s = (provider_or_name or "").lower()
    for key in ENV_KEY_PER_PLATFORM:
        if key in s:
            return key
    if "linked" in s:
        return "linkedin"
    if "insta" in s or s == "ig":
        return "instagram"
    if "tik" in s:
        return "tiktok"
    if "youtube" in s or s == "yt":
        return "youtube"
    return None


def update_env_file(env_path: Path, updates: dict[str, str]) -> int:
    """Replace or append KEY=VALUE lines for each entry in `updates`. Returns count of changes."""
    if not env_path.exists():
        env_path.write_text("")
    content = env_path.read_text()
    lines = content.splitlines()
    keys_present = set()
    new_lines: list[str] = []
    for line in lines:
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=", line)
        if m and m.group(1) in updates:
            new_lines.append(f"{m.group(1)}={updates[m.group(1)]}")
            keys_present.add(m.group(1))
        else:
            new_lines.append(line)
    # Append any missing
    for key, value in updates.items():
        if key not in keys_present:
            new_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(new_lines) + ("\n" if not content.endswith("\n") else ""))
    return len(updates)


def main() -> None:
    ap = argparse.ArgumentParser(description="Discover Postiz integration IDs")
    ap.add_argument("--write", action="store_true",
                    help="Update .env (and video-use/.env) with discovered IDs")
    ap.add_argument("--json", action="store_true", help="Print raw JSON response")
    args = ap.parse_args()

    api_url = _load_env_key_or_default("POSTIZ_API_URL", "http://localhost:5000")
    api_key = _load_env_key("POSTIZ_API_KEY")
    client = PostizClient(api_url, api_key)

    print(f"querying {api_url}/public/v1/integrations …")
    try:
        integrations = client.list_integrations()
    except PostizError as e:
        sys.exit(str(e))

    if args.json:
        print(json.dumps(integrations, indent=2, ensure_ascii=False))
        return

    if not integrations:
        print("no integrations found. Connect platforms in Postiz UI first.")
        return

    discovered: dict[str, str] = {}
    print()
    print(f"{'PLATFORM':<10} {'POSTIZ_ID':<40} {'NAME / PROVIDER'}")
    print("-" * 90)
    for it in integrations:
        provider = it.get("providerIdentifier") or it.get("provider") or it.get("type", "")
        name = it.get("name") or it.get("displayName") or it.get("identifier") or ""
        ig_id = it.get("id") or it.get("_id") or ""
        platform = normalize_platform(f"{provider} {name}")
        if not platform:
            print(f"{'?':<10} {str(ig_id):<40} {name} (unknown provider: {provider})")
            continue
        env_key = ENV_KEY_PER_PLATFORM[platform]
        # Pick the FIRST occurrence per platform (or override if name suggests "primary")
        if env_key not in discovered:
            discovered[env_key] = str(ig_id)
        print(f"{platform:<10} {str(ig_id):<40} {name}")

    if not discovered:
        print("\nno recognizable platform integrations found")
        return

    print()
    print("=== Ready to paste into .env ===")
    for env_key, ig_id in discovered.items():
        print(f"{env_key}={ig_id}")

    if args.write:
        env_files = [REPO_ROOT / ".env", REPO_ROOT / "video-use" / ".env"]
        for env_path in env_files:
            n = update_env_file(env_path, discovered)
            print(f"\nupdated {env_path.relative_to(REPO_ROOT)} ({n} keys)")


def _load_env_key_or_default(name: str, default: str) -> str:
    """Like _load_env_key but returns default instead of exiting."""
    try:
        return _load_env_key(name)
    except SystemExit:
        return default


if __name__ == "__main__":
    main()
