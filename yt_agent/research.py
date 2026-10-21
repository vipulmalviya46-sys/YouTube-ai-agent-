"""Viral research: find outlier videos in the niche, mine title/hook patterns, produce ranked ideas.

Outlier score = views / max(channel subscribers, 1000). A small channel with a huge video means the
*topic/packaging* worked, not the channel's audience - that's the signal worth copying (the idea, never the video).
Quota: search.list = 100 units, videos.list/channels.list/playlistItems.list = 1 unit (10k units/day default).
"""
from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from .config import Settings
from .llm import LLM


@dataclass
class VideoSignal:
    id: str
    title: str
    channel: str
    subs: int
    views: int
    hours_old: float
    vph: float
    outlier: float
    url: str


@dataclass
class Idea:
    title: str
    angle: str
    hook: str
    why_it_works: str
    keywords: list
    score: float


def _yt():
    from googleapiclient.discovery import build

    return build("youtube", "v3", developerKey=os.environ["YOUTUBE_API_KEY"], cache_discovery=False)


def _signals_from_ids(yt, ids: list[str]) -> list[VideoSignal]:
    if not ids:
        return []
    vids = yt.videos().list(part="snippet,statistics", id=",".join(ids[:50])).execute()["items"]
    chan_ids = list({v["snippet"]["channelId"] for v in vids})
    subs = {
        c["id"]: int(c["statistics"].get("subscriberCount", 0))
        for c in yt.channels().list(part="statistics", id=",".join(chan_ids)).execute()["items"]
    }
    now = datetime.now(timezone.utc)
    out = []
    for v in vids:
        views = int(v["statistics"].get("viewCount", 0))
        pub = datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00"))
        hours = max((now - pub).total_seconds() / 3600, 1)
        s = subs.get(v["snippet"]["channelId"], 0)
        out.append(
            VideoSignal(
                id=v["id"], title=v["snippet"]["title"], channel=v["snippet"]["channelTitle"], subs=s,
                views=views, hours_old=round(hours, 1), vph=round(views / hours, 1),
                outlier=round(views / max(s, 1000), 2), url=f"https://youtu.be/{v['id']}",
            )
        )
    return out


def fetch_signals(cfg: Settings, max_results: int = 25) -> list[VideoSignal]:
    """Niche search (recent, by views) + competitor channels' latest uploads."""
    if not os.getenv("YOUTUBE_API_KEY"):
        print("[research] no YOUTUBE_API_KEY - skipping live YouTube signals")
        return []
    yt = _yt()
    after = (datetime.now(timezone.utc) - timedelta(days=cfg.research_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = yt.search().list(
        q=cfg.niche, part="id", type="video", order="viewCount", publishedAfter=after,
        maxResults=max_results, regionCode=cfg.region, relevanceLanguage=cfg.language,
    ).execute()
    ids = [i["id"]["videoId"] for i in res.get("items", [])]
    for ch in cfg.competitor_channel_ids:  # uploads playlist id = "UU" + channel id[2:]
        pl = yt.playlistItems().list(part="contentDetails", playlistId="UU" + ch[2:], maxResults=10).execute()
        ids += [i["contentDetails"]["videoId"] for i in pl.get("items", [])]
    sigs = _signals_from_ids(yt, list(dict.fromkeys(ids)))
    return sorted(sigs, key=lambda s: s.outlier * math.log10(s.views + 10), reverse=True)


def fetch_trends(cfg: Settings) -> list[str]:
    """Rising related queries from Google Trends (optional dependency, best effort)."""
    try:
        from pytrends.request import TrendReq

        t = TrendReq(hl=cfg.language, tz=0)
        t.build_payload([cfg.niche], timeframe="now 7-d", geo=cfg.region)
        rising = t.related_queries().get(cfg.niche, {}).get("rising")
        return [] if rising is None else rising["query"].head(10).tolist()
    except Exception as e:  # noqa: BLE001
        print(f"[research] trends unavailable: {e}")
        return []


SYSTEM = (
    "You are a YouTube strategist who studies why videos break out. You identify transferable PATTERNS "
    "(topic, curiosity gap, specificity, title structure, hook type) and propose ORIGINAL ideas. "
    "Never suggest copying a video; never propose misleading titles/thumbnails."
)


def generate_ideas(cfg: Settings, llm: LLM, signals: list[VideoSignal], trends: list[str], n: int = 8) -> list[Idea]:
    top = "\n".join(
        f"- {s.title} | {s.views:,} views | {s.subs:,} subs | outlier x{s.outlier} | {s.vph:.0f} views/h"
        for s in signals[:15]
    ) or "(no live data available)"
    prompt = f"""Niche: {cfg.niche}
Channel voice: {cfg.channel_voice}
Top recent outlier videos:\n{top}
Rising searches: {', '.join(trends) or 'n/a'}

Return a JSON list of {n} ORIGINAL video ideas sorted best-first. Each item:
{{"title": str (<=60 chars, specific, honest curiosity gap), "angle": str, "hook": str (first 15 seconds),
"why_it_works": str (which pattern from the data), "keywords": [str], "score": number 1-10}}"""
    fallback = [
        {
            "title": (s.title[:58] if s.title else f"{cfg.niche}: what nobody tells you"),
            "angle": f"Fresh take on a proven topic in {cfg.niche}",
            "hook": f"Most people get {cfg.niche} wrong. Here's what actually works.",
            "why_it_works": f"Outlier x{s.outlier} on a {s.subs:,}-sub channel",
            "keywords": cfg.niche.split(),
            "score": min(10, 5 + s.outlier / 5),
        }
        for s in signals[:n]
    ] or [
        {
            "title": f"{cfg.niche}: the 5-minute setup that changes everything",
            "angle": "Practical beginner walkthrough",
            "hook": f"If you're into {cfg.niche}, you're probably wasting hours. Let's fix that.",
            "why_it_works": "evergreen how-to",
            "keywords": cfg.niche.split(),
            "score": 6,
        }
    ]
    raw = llm.json(SYSTEM, prompt, fallback)
    raw = [i for i in raw if isinstance(i, dict)] or fallback
    return [Idea(**{k: i.get(k, "" if k != "keywords" else []) for k in Idea.__dataclass_fields__}) for i in raw]


def research(cfg: Settings, llm: LLM, state=None) -> tuple[list[VideoSignal], list[Idea]]:
    signals = fetch_signals(cfg)
    ideas = generate_ideas(cfg, llm, signals, fetch_trends(cfg))
    if state:
        ideas = [i for i in ideas if not state.idea_used(i.title)] or ideas
    return signals, sorted(ideas, key=lambda i: i.score, reverse=True)


def to_dict(x):
    return asdict(x)
