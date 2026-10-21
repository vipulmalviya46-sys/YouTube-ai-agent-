"""YouTube Data API v3: OAuth, resumable upload, thumbnail, scheduling, comments, stats.

Quota (default 10,000 units/day): videos.insert = 1600, thumbnails.set = 50, comments.insert = 50,
commentThreads.list = 1. So: ~5 uploads/day max, or fewer if you also reply a lot.
NOTE: videos uploaded by an API project that hasn't passed YouTube's API compliance audit are locked to
private. Request the audit (Google Cloud console -> YouTube API Services) before expecting public uploads.
"""
from __future__ import annotations

import os
import random
import time
from pathlib import Path

from .config import ROOT

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
TOKEN = ROOT / "token.json"


def service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES) if TOKEN.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            secrets = os.getenv("YOUTUBE_CLIENT_SECRETS", "client_secret.json")
            flow = InstalledAppFlow.from_client_secrets_file(secrets, SCOPES)
            if os.getenv("YT_MANUAL_AUTH"):  # phone / cloud terminal: no local browser available
                os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
                flow.redirect_uri = "http://localhost:8080/"
                url, _ = flow.authorization_url(prompt="consent", access_type="offline")
                print("\n1) Open this link, sign in, press Allow:\n" + url)
                print("2) The next page will fail to load (that's expected). Copy the FULL address from the address bar.")
                flow.fetch_token(authorization_response=input("3) Paste it here: ").strip())
                creds = flow.credentials
            else:
                creds = flow.run_local_server(port=0)
        TOKEN.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload_video(path: Path, title: str, description: str, tags: list[str], category_id: str = "28",
                 privacy: str = "private", publish_at: str | None = None, synthetic: bool = True,
                 language: str = "en") -> str:
    """publish_at: RFC3339 UTC (e.g. 2026-10-21T14:00:00Z). Scheduling requires privacy='private'."""
    from googleapiclient.http import MediaFileUpload

    yt = service()
    status = {"privacyStatus": "private" if publish_at else privacy, "selfDeclaredMadeForKids": False,
              "containsSyntheticMedia": synthetic}
    if publish_at:
        status["publishAt"] = publish_at
    body = {
        "snippet": {"title": title[:100], "description": description[:5000], "tags": tags,
                    "categoryId": category_id, "defaultLanguage": language, "defaultAudioLanguage": language},
        "status": status,
    }
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(path), chunksize=8 * 1024 * 1024, resumable=True))
    resp, retries = None, 0
    while resp is None:
        try:
            _, resp = req.next_chunk()
        except Exception as e:  # noqa: BLE001  (transient 5xx / network)
            retries += 1
            if retries > 8:
                raise
            time.sleep(min(60, 2 ** retries + random.random()))
            print(f"[upload] retry {retries}: {e}")
    return resp["id"]


def set_thumbnail(video_id: str, image: Path):
    from googleapiclient.http import MediaFileUpload

    service().thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(image), mimetype="image/jpeg")).execute()


def my_channel_id() -> str:
    return service().channels().list(part="id", mine=True).execute()["items"][0]["id"]


def new_comments(video_id: str, limit: int = 50) -> list[dict]:
    yt = service()
    mine = my_channel_id()
    res = yt.commentThreads().list(part="snippet", videoId=video_id, order="time", maxResults=min(limit, 100),
                                   textFormat="plainText").execute()
    out = []
    for it in res.get("items", []):
        top = it["snippet"]["topLevelComment"]
        s = top["snippet"]
        if s.get("authorChannelId", {}).get("value") == mine or it["snippet"]["totalReplyCount"] > 0:
            continue  # own comment, or already has a reply
        out.append({"id": top["id"], "video_id": video_id, "author": s["authorDisplayName"], "text": s["textDisplay"]})
    return out


def reply(comment_id: str, text: str):
    service().comments().insert(part="snippet", body={"snippet": {"parentId": comment_id, "textOriginal": text}}).execute()


def stats(video_ids: list[str]) -> dict:
    items = service().videos().list(part="statistics", id=",".join(video_ids)).execute().get("items", [])
    return {i["id"]: i["statistics"] for i in items}
