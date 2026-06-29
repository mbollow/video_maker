"""GoHighLevel (LeadConnector) Social Planner API client.

Lightweight `requests`-based wrapper for the GHL API v2 Social Media Posting
endpoints. Used by ghl_discover.py (read-only) and ghl_push.py to upload media
and create social planner posts (draft / scheduled).

API reference:
    https://marketplace.gohighlevel.com/docs/ghl/social-planner/social-media-posting-api
    https://marketplace.gohighlevel.com/docs/Authorization/PrivateIntegrationsToken/

Auth: Private Integration Token (PIT). Header shape:
    Authorization: Bearer <GHL_PRIVATE_INTEGRATION_TOKEN>
    Version: 2021-07-28

NOTE: the GHL marketplace docs are a JS-rendered SPA, so the exact request/
response shapes can't be scraped. The shapes below are best-effort; if a call
fails with 4xx, run `ghl_discover.py --json` (or curl) to inspect the real
payload and adjust. Discover is intentionally read-only so we verify auth +
account shapes BEFORE attempting any write.

Usage:
    from ghl_client import GHLClient
    client = GHLClient(token, location_id)
    accounts = client.list_accounts()          # read-only
    media = client.upload_media(Path("final.mp4"))
    resp = client.create_post(
        account_ids=["acc1"],
        summary="caption text",
        media=[media],
        status="draft",
    )
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://services.leadconnectorhq.com"
API_VERSION = "2021-07-28"


@dataclass
class GHLError(Exception):
    status_code: int
    body: str
    endpoint: str

    def __str__(self) -> str:
        return f"GHL {self.endpoint} returned {self.status_code}: {self.body[:400]}"


class GHLClient:
    def __init__(self, token: str, location_id: str, timeout: int = 120):
        self.token = token
        self.location_id = location_id
        self.timeout = timeout

    # -------- HTTP plumbing --------------------------------------------------

    def _headers(self, extra: dict | None = None) -> dict:
        h = {
            "Authorization": f"Bearer {self.token}",
            "Version": API_VERSION,
            "Accept": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    def _request(self, method: str, path: str, *, payload: dict | None = None,
                 params: dict | None = None) -> dict:
        url = f"{BASE_URL}{path}"
        resp = requests.request(
            method,
            url,
            headers=self._headers({"Content-Type": "application/json"} if payload else None),
            json=payload,
            params=params,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise GHLError(resp.status_code, resp.text, f"{method} {path}")
        try:
            return resp.json()
        except json.JSONDecodeError:
            return {"raw": resp.text}

    # -------- Accounts (read-only) -------------------------------------------

    def list_accounts(self) -> dict:
        """List social planner accounts connected for this location.

        GET /social-media-posting/{locationId}/accounts
        Returns the raw response dict (real shape: {"results": {"accounts": [...]}}).
        """
        return self._request(
            "GET", f"/social-media-posting/{self.location_id}/accounts"
        )

    def account_platform_map(self) -> dict:
        """Return {account_id: platform_lowercase} for connected accounts."""
        resp = self.list_accounts()
        accounts = None
        if isinstance(resp, dict):
            res = resp.get("results")
            accounts = res.get("accounts") if isinstance(res, dict) else resp.get("accounts")
        if accounts is None and isinstance(resp, list):
            accounts = resp
        out: dict = {}
        for a in accounts or []:
            aid = a.get("id") or a.get("_id")
            plat = (a.get("platform") or a.get("type") or a.get("provider") or "").lower()
            if aid:
                out[str(aid)] = plat
        return out

    def list_posts(self, limit: int = 20, skip: int = 0) -> list[dict]:
        """List existing social planner posts.

        POST /social-media-posting/{locationId}/posts/list
        NOTE: limit/skip must be sent as STRINGS (API quirk).
        Returns the list of post dicts (best-effort across response shapes).
        """
        resp = self._request(
            "POST", f"/social-media-posting/{self.location_id}/posts/list",
            payload={"limit": str(limit), "skip": str(skip)},
        )
        res = resp.get("results") if isinstance(resp, dict) else None
        if isinstance(res, dict) and "posts" in res:
            return res["posts"]
        if isinstance(res, list):
            return res
        return resp.get("posts", []) if isinstance(resp, dict) else []

    def search_posts(
        self,
        *,
        post_status: str = "all",
        accounts: list[str] | None = None,
        from_date: "datetime | None" = None,
        to_date: "datetime | None" = None,
        limit: int = 100,
        skip: int = 0,
    ) -> list[dict]:
        """Search posts with filters (POST /social-media-posting/{loc}/posts/list).

        SearchPostDTO fields are STRINGS (API quirk): type, accounts (comma-
        joined ids), fromDate/toDate (ISO), limit, skip. `post_status` maps to
        the API `type` filter: recent|all|scheduled|draft|published|...
        """
        body: dict[str, Any] = {
            "type": post_status,
            "limit": str(limit),
            "skip": str(skip),
        }
        if accounts:
            body["accounts"] = ", ".join(accounts)
        if from_date is not None:
            body["fromDate"] = from_date.astimezone().isoformat()
        if to_date is not None:
            body["toDate"] = to_date.astimezone().isoformat()
        resp = self._request(
            "POST", f"/social-media-posting/{self.location_id}/posts/list",
            payload=body,
        )
        res = resp.get("results") if isinstance(resp, dict) else None
        if isinstance(res, dict) and "posts" in res:
            return res["posts"]
        if isinstance(res, list):
            return res
        return resp.get("posts", []) if isinstance(resp, dict) else []

    def harvest_user_id(self) -> str | None:
        """Find a valid GHL userId from existing posts' createdBy field.

        The Social Planner create-post API requires a userId, but listing users
        needs a separate scope the PIT may not have. Existing posts expose the
        creating user's id via createdBy, which is a valid userId to reuse.
        """
        posts = self.list_posts(limit=20)
        counts: dict[str, int] = {}
        for p in posts:
            for key in ("userId", "createdBy"):
                v = p.get(key)
                if isinstance(v, dict):
                    v = v.get("id") or v.get("userId")
                if v:
                    counts[str(v)] = counts.get(str(v), 0) + 1
        if not counts:
            return None
        return max(counts, key=counts.get)

    # -------- Media upload ---------------------------------------------------

    def upload_media(self, video_path: Path, file_name: str | None = None) -> dict:
        """Upload a media file to the GHL Media Library.

        POST /medias/upload-file  (multipart, field "file")
        Form also carries the location target (altType/altId).
        `file_name` overrides the name shown in the GHL media library (defaults
        to the local filename). Returns a dict normalized to {"id", "url"} when
        possible, else the raw response so the caller can inspect.
        """
        url = f"{BASE_URL}/medias/upload-file"
        name = file_name or video_path.name
        with open(video_path, "rb") as f:
            files = {"file": (name, f, "video/mp4")}
            data = {
                "hosted": "false",
                "fileName": name,
                "altType": "location",
                "altId": self.location_id,
            }
            resp = requests.post(
                url,
                headers=self._headers(),  # no Content-Type: requests sets multipart boundary
                files=files,
                data=data,
                timeout=self.timeout * 6,  # uploads take longer
            )
        if resp.status_code >= 400:
            raise GHLError(resp.status_code, resp.text, "POST /medias/upload-file")
        try:
            body = resp.json()
        except json.JSONDecodeError:
            raise GHLError(200, f"non-JSON upload response: {resp.text[:300]}",
                           "POST /medias/upload-file")
        file_id = body.get("fileId") or body.get("id") or body.get("_id")
        media_url = body.get("url") or body.get("fileUrl") or body.get("location")
        return {"id": file_id, "url": media_url, "raw": body}

    # -------- Post creation --------------------------------------------------

    def create_post(
        self,
        *,
        account_ids: list[str],
        summary: str,
        user_id: str,
        media: list[dict] | None = None,
        status: str = "draft",
        post_type: str = "post",
        schedule_date: datetime | None = None,
        extra_fields: dict | None = None,
    ) -> dict:
        """Create a social planner post for one or more connected accounts.

        POST /social-media-posting/{locationId}/posts

        Per the official CreatePostDTO schema:
            - `type`   is the POST KIND: "post" | "story" | "reel"
            - `status` is the LIFECYCLE: "draft" | "scheduled" | "published" | ...
            - `userId` is REQUIRED (the authoring GHL user)
            - media item `type` is a MIME type, e.g. "video/mp4" / "image/png"

        Args:
            account_ids: GHL social account ids (from list_accounts)
            summary: caption / post text
            user_id: authoring GHL user id (required by the API)
            media: list of {"url", "type" (mime), "id"} entries
            status: post lifecycle status (default "draft")
            post_type: "post" | "story" | "reel" (default "post")
            schedule_date: tz-aware datetime, required when status == "scheduled"
            extra_fields: merged into the request body (platform-specific options)

        Returns the raw GHL response dict.
        """
        if status not in ("draft", "scheduled", "published"):
            raise ValueError(f"invalid status: {status}")
        if post_type not in ("post", "story", "reel"):
            raise ValueError(f"invalid post_type: {post_type}")

        payload: dict[str, Any] = {
            "accountIds": account_ids,
            "userId": user_id,
            "summary": summary,
            "type": post_type,
            "status": status,
        }
        if media:
            payload["media"] = media
        if status == "scheduled" and schedule_date is None:
            raise ValueError("schedule_date required when status == 'scheduled'")
        # A draft may also carry a scheduleDate so the intended slot is pre-filled
        # in the GHL composer (and occupies that day for distribution).
        if schedule_date is not None:
            payload["scheduleDate"] = schedule_date.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.000Z"
            )
        if extra_fields:
            payload.update(extra_fields)

        return self._request(
            "POST", f"/social-media-posting/{self.location_id}/posts", payload=payload
        )

    def get_post(self, post_id: str) -> dict:
        return self._request(
            "GET", f"/social-media-posting/{self.location_id}/posts/{post_id}"
        )

    def delete_post(self, post_id: str) -> dict:
        """Delete a post (DELETE /social-media-posting/{loc}/posts/{id})."""
        return self._request(
            "DELETE", f"/social-media-posting/{self.location_id}/posts/{post_id}"
        )

    def update_post(self, post_id: str, payload: dict) -> dict:
        """Update an existing post (PUT /social-media-posting/{loc}/posts/{id}).

        `payload` should carry the full post fields (type is required); resend
        the existing values plus whatever you want to change so GHL does not drop
        fields. Datetimes in `scheduleDate` must already be ISO strings.
        """
        return self._request(
            "PUT", f"/social-media-posting/{self.location_id}/posts/{post_id}",
            payload=payload,
        )
