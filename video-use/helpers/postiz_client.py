"""Postiz Public API client.

Lightweight `requests`-based wrapper for the Postiz `/public/v1/*` endpoints.
Used by postiz_push.py to upload media and create scheduled posts.

Postiz API reference: https://docs.postiz.com/public-api

NOTE: Postiz's public API surface evolves. If a call fails with 4xx, run
    `curl -H "Authorization: Bearer $POSTIZ_API_KEY" $POSTIZ_API_URL/public/v1/...`
to inspect the actual shape, then adjust this client. The verify checklist
in postiz/README.md walks through this.

Usage:
    from postiz_client import PostizClient
    client = PostizClient(api_url, api_key)
    media_id = client.upload_media(Path("renders/final.mp4"))
    resp = client.create_post(
        integration_id="abc123",
        content="caption text",
        media_id=media_id,
        scheduled_at=datetime(2026, 5, 30, 9, 15, tzinfo=ZoneInfo("Europe/Berlin")),
        platform="LINKEDIN",
    )
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


@dataclass
class PostizError(Exception):
    status_code: int
    body: str
    endpoint: str

    def __str__(self) -> str:
        return f"Postiz {self.endpoint} returned {self.status_code}: {self.body[:300]}"


class PostizClient:
    def __init__(self, api_url: str, api_key: str, timeout: int = 120):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    # -------- HTTP plumbing --------------------------------------------------

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Authorization": f"Bearer {self.api_key}"}
        if extra:
            h.update(extra)
        return h

    def _json_request(self, method: str, path: str, payload: dict | None = None) -> dict:
        url = f"{self.api_url}{path}"
        resp = requests.request(
            method,
            url,
            headers=self._headers({"Content-Type": "application/json"}),
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise PostizError(resp.status_code, resp.text, f"{method} {path}")
        try:
            return resp.json()
        except json.JSONDecodeError:
            return {"raw": resp.text}

    # -------- Media upload ---------------------------------------------------

    def upload_media(self, video_path: Path) -> str:
        """Upload a media file. Returns the media id reference.

        Postiz endpoint shape (most recent observed):
            POST /public/v1/upload  (multipart, field name "file")
            Response: {"id": "...", "path": "..."} or similar
        """
        url = f"{self.api_url}/public/v1/upload"
        with open(video_path, "rb") as f:
            files = {"file": (video_path.name, f, "video/mp4")}
            resp = requests.post(
                url,
                headers=self._headers(),
                files=files,
                timeout=self.timeout * 4,  # uploads take longer
            )
        if resp.status_code >= 400:
            raise PostizError(resp.status_code, resp.text, "POST /public/v1/upload")
        data = resp.json()
        # Try common id field names
        for key in ("id", "_id", "mediaId", "uploadId"):
            if key in data:
                return str(data[key])
        # If response has a list, return first
        if isinstance(data, list) and data and "id" in data[0]:
            return str(data[0]["id"])
        raise PostizError(200, f"unexpected upload response: {data}", "POST /public/v1/upload")

    # -------- Post creation --------------------------------------------------

    PLATFORM_TYPE_MAP = {
        "linkedin": "LINKEDIN",
        "instagram": "INSTAGRAM",
        "tiktok": "TIKTOK",
        "youtube": "YOUTUBE",
    }

    def create_post(
        self,
        *,
        integration_id: str,
        platform: str,
        content: str,
        media_id: str,
        scheduled_at: datetime | None,
        draft: bool = False,
        platform_settings: dict | None = None,
        extra_post_fields: dict | None = None,
    ) -> dict:
        """Create a scheduled post for ONE platform.

        Args:
            integration_id: Postiz integration id (one per platform connected)
            platform: 'linkedin' | 'instagram' | 'tiktok' | 'youtube'
            content: caption text
            media_id: media id returned from upload_media()
            scheduled_at: tz-aware datetime; None or `draft=True` posts as draft
            draft: if True, posts as draft instead of scheduling live
            platform_settings: optional dict of __type-specific fields
            extra_post_fields: optional extra fields merged into the post dict

        Returns the full Postiz response body.
        """
        platform_lower = platform.lower()
        platform_type = self.PLATFORM_TYPE_MAP.get(platform_lower)
        if not platform_type:
            raise ValueError(f"unknown platform: {platform}")

        # Settings object expected by Postiz per platform
        settings = {"__type": platform_type}
        if platform_settings:
            settings.update(platform_settings)

        post_obj: dict[str, Any] = {
            "integration": {"id": integration_id},
            "value": [{"content": content, "id": media_id}],
            "settings": settings,
        }
        if extra_post_fields:
            post_obj.update(extra_post_fields)

        payload: dict[str, Any] = {
            "type": "draft" if draft else "schedule",
            "posts": [post_obj],
        }
        if not draft and scheduled_at is not None:
            payload["date"] = scheduled_at.isoformat()

        return self._json_request("POST", "/public/v1/posts", payload)

    # -------- Lookup ---------------------------------------------------------

    def get_post(self, post_id: str) -> dict:
        return self._json_request("GET", f"/public/v1/posts/{post_id}")

    def list_integrations(self) -> list[dict]:
        """List connected platform integrations. Useful to find integration IDs after OAuth."""
        data = self._json_request("GET", "/public/v1/integrations")
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return [data]


# -------- High-level helper used by postiz_push.py ---------------------------


def post_video_to_postiz(
    *,
    client: PostizClient,
    video_path: Path,
    posts_to_publish: list[dict],
    draft: bool = False,
    upload_retry: int = 2,
) -> dict[str, dict]:
    """Upload the video once, then create one Postiz post per platform.

    Args:
        client: PostizClient
        video_path: path to the rendered video
        posts_to_publish: list of dicts, each:
            {
                "platform": "linkedin" | ...,
                "integration_id": "...",
                "content": "caption text",
                "scheduled_at": datetime | None,
            }
        draft: if True, post all as drafts (sandbox mode)

    Returns: {platform: {"status": "pushed" | "failed", "post_id": "...", "error": "..."}}
    """
    results: dict[str, dict] = {}

    # 1. Upload once
    last_err: Exception | None = None
    media_id: str | None = None
    for attempt in range(1, upload_retry + 1):
        try:
            media_id = client.upload_media(video_path)
            break
        except Exception as e:
            last_err = e
            time.sleep(min(2 ** attempt, 30))
    if media_id is None:
        for pr in posts_to_publish:
            results[pr["platform"]] = {"status": "failed", "error": f"upload failed: {last_err}"}
        return results

    # 2. One create_post per platform
    for pr in posts_to_publish:
        platform = pr["platform"]
        try:
            resp = client.create_post(
                integration_id=pr["integration_id"],
                platform=platform,
                content=pr["content"],
                media_id=media_id,
                scheduled_at=pr.get("scheduled_at"),
                draft=draft,
                platform_settings=pr.get("platform_settings"),
            )
            # Extract a post_id if possible
            post_id = None
            if isinstance(resp, dict):
                post_id = resp.get("id") or resp.get("_id")
                if not post_id and "posts" in resp and resp["posts"]:
                    post_id = resp["posts"][0].get("id")
            results[platform] = {
                "status": "pushed",
                "post_id": post_id,
                "response": resp,
            }
        except Exception as e:
            results[platform] = {"status": "failed", "error": str(e)}

    return results
