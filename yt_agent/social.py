"""Distribution: platform-native promo copy, a vertical teaser clip, and posting where an official API exists
(Telegram, Discord webhook, X). Everything else is written as ready-to-paste drafts - Reddit, TikTok,
Instagram and LinkedIn actively punish bot-posted promo, so a human taps 'post' there."""
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from .config import Settings
from .llm import LLM
from .script import Script

SYSTEM = """You are a social media growth editor. Write native-feeling promo for a new YouTube video.
Each platform gets a different angle - never paste the same text. Value first, link last, no engagement bait,
no fake urgency, no misleading claims. Max 2 hashtags (none on Reddit)."""


def promo_copy(cfg: Settings, llm: LLM, script: Script, url: str) -> dict:
    prompt = f"""Video: {script.title}\nURL: {url}\nSummary: {script.description[:400]}\nNiche: {cfg.niche}
JSON object with keys: x_thread (list of 3-5 tweets, first is the hook), reddit (object: title, body - give
the value in the post, mention the video at the end, name suitable subreddits in 'subreddits'),
linkedin (str), instagram_caption (str), tiktok_caption (str), community_post (str, YouTube Community tab),
telegram (str), discord (str), shorts_title (str <=60), shorts_description (str)."""
    fallback = {
        "x_thread": [f"{script.title}\n\n{url}"], "reddit": {"title": script.title, "body": url, "subreddits": []},
        "linkedin": f"{script.title}\n{url}", "instagram_caption": script.title, "tiktok_caption": script.title,
        "community_post": f"New video: {script.title}\n{url}", "telegram": f"{script.title}\n{url}",
        "discord": f"**{script.title}**\n{url}", "shorts_title": script.title[:60], "shorts_description": url,
    }
    return llm.json(SYSTEM, prompt, fallback, max_tokens=3000)


def post_telegram(text: str):
    t, c = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if t and c:
        requests.post(f"https://api.telegram.org/bot{t}/sendMessage", json={"chat_id": c, "text": text}, timeout=30).raise_for_status()
        return True


def post_discord(text: str):
    if (u := os.getenv("DISCORD_WEBHOOK_URL")):
        requests.post(u, json={"content": text}, timeout=30).raise_for_status()
        return True


def post_x_thread(tweets: list[str]):
    keys = [os.getenv(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")]
    if not all(keys):
        return False
    import tweepy

    client = tweepy.Client(consumer_key=keys[0], consumer_secret=keys[1], access_token=keys[2], access_token_secret=keys[3])
    prev = None
    for t in tweets:
        r = client.create_tweet(text=t[:280], in_reply_to_tweet_id=prev)
        prev = r.data["id"]
    return True


def promote(cfg: Settings, llm: LLM, script: Script, video_id: str, out_dir: Path, post: bool = True) -> dict:
    url = f"https://youtu.be/{video_id}"
    copy = promo_copy(cfg, llm, script, url)
    (out_dir / "promo.json").write_text(json.dumps(copy, indent=2, ensure_ascii=False))
    posted = []
    if post:
        for name, fn, arg in (("telegram", post_telegram, copy.get("telegram", "")),
                              ("discord", post_discord, copy.get("discord", "")),
                              ("x", post_x_thread, copy.get("x_thread", []))):
            try:
                if arg and fn(arg):
                    posted.append(name)
            except Exception as e:  # noqa: BLE001
                print(f"[social] {name} failed: {e}")
    return {"posted": posted, "drafts": str(out_dir / "promo.json")}
