"""Pexels stock-photo adapter for the Bild-Post pipeline.

Used when a post should NOT carry Juliana's face — e.g. provocative "problem"
hooks where a portrait would read as "she has this problem". Pulls a fitting
conceptual photo from Pexels (free, no attribution required) on demand.

Needs PEXELS_API_KEY in .env (free key at https://www.pexels.com/api/).
"""

from __future__ import annotations

from pathlib import Path

import requests

PEXELS_SEARCH = "https://api.pexels.com/v1/search"


def search_pexels(query: str, api_key: str, *, orientation: str = "portrait",
                  per_page: int = 15) -> list[dict]:
    r = requests.get(
        PEXELS_SEARCH,
        headers={"Authorization": api_key},
        params={"query": query, "orientation": orientation, "per_page": per_page},
        timeout=20,
    )
    r.raise_for_status()
    return r.json().get("photos", [])


def pick_and_download(photos: list[dict], used_ids: set[int], dest_dir: Path) -> dict | None:
    """Pick the first not-yet-used photo, download it, return its metadata.

    Returns None if nothing usable was found.
    """
    for p in photos:
        if p["id"] in used_ids:
            continue
        src = p.get("src", {})
        url = src.get("large2x") or src.get("portrait") or src.get("large")
        if not url:
            continue
        img = requests.get(url, timeout=30)
        img.raise_for_status()
        path = Path(dest_dir) / f"pexels_{p['id']}.jpg"
        path.write_bytes(img.content)
        return {
            "path": path,
            "provider": "pexels",
            "id": p["id"],
            "photographer": p.get("photographer"),
            "url": p.get("url"),
            "src_url": url,
            "alt": p.get("alt"),
        }
    return None


def download_url(url: str, dest_dir: Path, ident) -> Path:
    """Re-download a known Pexels image URL (used to preserve a post's image
    across text-only rebuilds)."""
    img = requests.get(url, timeout=30)
    img.raise_for_status()
    path = Path(dest_dir) / f"pexels_{ident}.jpg"
    path.write_bytes(img.content)
    return path


def fetch_stock(query: str, api_key: str, used_ids: set[int], dest_dir: Path) -> dict | None:
    """Search + download in one call. Falls back to landscape if portrait is empty."""
    photos = search_pexels(query, api_key, orientation="portrait")
    if not photos:
        photos = search_pexels(query, api_key, orientation="landscape")
    return pick_and_download(photos, used_ids, dest_dir)
