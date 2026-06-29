"""Publish ledger for GoHighLevel — prevents accidental double-publishing.

Records which video (identified by SHA-256 of its bytes, so renames/duplicate
filenames don't fool it) was published to which GHL account, when, and with
which post/media ids. The ledger lives in the repo root as `ghl_publish_log.json`
so it is committed to git and shared across machines.

Dedup is per (video, account): re-pushing the same file to an account it has
already gone to is blocked; pushing it to a NEW account is allowed; a corrected
re-render has a different hash and is therefore treated as a new video.

Usage (library):
    from ghl_ledger import (load_ledger, sha256_file, published_accounts_for,
                            append_entry)
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEDGER_PATH = REPO_ROOT / "ghl_publish_log.json"
LEDGER_VERSION = 1


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def load_ledger(path: Path = LEDGER_PATH) -> dict:
    if not path.exists():
        return {"version": LEDGER_VERSION, "entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": LEDGER_VERSION, "entries": []}
    data.setdefault("version", LEDGER_VERSION)
    data.setdefault("entries", [])
    return data


def save_ledger(ledger: dict, path: Path = LEDGER_PATH) -> None:
    """Atomic write so a crash never corrupts the ledger."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def entries_for(ledger: dict, sha: str) -> list[dict]:
    return [e for e in ledger.get("entries", []) if e.get("sha256") == sha]


def published_accounts_for(ledger: dict, sha: str) -> set[str]:
    """All account ids this video has already been published to."""
    accts: set[str] = set()
    for e in entries_for(ledger, sha):
        accts.update(e.get("account_ids") or [])
    return accts


def append_entry(
    ledger: dict,
    *,
    sha: str,
    folder: str | None,
    media_name: str,
    source_path: str,
    size_bytes: int,
    account_ids: list[str],
    published_at: str,
    post_id: str | None,
    media_id: str | None,
    media_url: str | None,
    status: str,
    schedule_date: str | None,
    path: Path = LEDGER_PATH,
) -> dict:
    entry = {
        "sha256": sha,
        "folder": folder,
        "media_name": media_name,
        "source_path": source_path,
        "size_bytes": size_bytes,
        "account_ids": account_ids,
        "published_at": published_at,
        "post_id": post_id,
        "media_id": media_id,
        "media_url": media_url,
        "status": status,
        "schedule_date": schedule_date,
    }
    ledger.setdefault("entries", []).append(entry)
    save_ledger(ledger, path)
    return entry
