"""Comment engagement: classify -> draft in the channel's voice -> approval queue (default) or auto-post.

Guardrails (to stay inside YouTube's spam/automation policies and keep the channel human-feeling):
 * skip spam / toxic / scams / anything asking for personal info, never include links in replies
 * only reply to substantive comments (questions, feedback, thoughtful praise), capped per run
 * randomised delay between posts; never reply twice; default mode = human approves the queue
"""
from __future__ import annotations

import random
import re
import time

from . import youtube
from .config import Settings
from .llm import LLM
from .state import State

SYSTEM = """You manage comments for a YouTube creator. Classify and answer each comment.
Voice: {voice}
Rules: reply in the commenter's language, 1-2 sentences, specific to what they said, no links, no hashtags,
no promises you can't keep, no medical/legal/financial advice. If it's spam, a scam, hateful, or a bait to
argue, set action to "skip". Praise -> short genuine thanks + one engaging question. Question -> concise answer.
Return a JSON list: [{{"id": str, "action": "reply"|"skip", "category": str, "reply": str}}]."""

LINK = re.compile(r"https?://|www\.", re.I)


def draft_replies(cfg: Settings, llm: LLM, comments: list[dict]) -> list[dict]:
    if not comments:
        return []
    payload = "\n".join(f'{c["id"]} | {c["author"]}: {c["text"][:400]}' for c in comments)
    decisions = llm.json(SYSTEM.format(voice=cfg.channel_voice), payload, fallback=[], max_tokens=3000)
    by_id = {c["id"]: c for c in comments}
    out = []
    for d in decisions:
        c = by_id.get(d.get("id"))
        if not c or d.get("action") != "reply" or not d.get("reply") or LINK.search(d["reply"]):
            continue
        out.append({**c, "reply": d["reply"].strip()[:500], "category": d.get("category", "")})
    return out


def run_engagement(cfg: Settings, llm: LLM, state: State) -> dict:
    """Scan recent videos, draft replies; post (auto_reply) or queue (default)."""
    stats = {"seen": 0, "queued": 0, "posted": 0}
    for vid in state.recent_video_ids():
        fresh = [c for c in youtube.new_comments(vid) if not state.already_replied(c["id"])]
        stats["seen"] += len(fresh)
        for d in draft_replies(cfg, llm, fresh)[: cfg.max_replies_per_run]:
            if cfg.auto_reply and stats["posted"] < cfg.max_replies_per_run:
                time.sleep(random.uniform(cfg.reply_min_delay_s, cfg.reply_max_delay_s))
                youtube.reply(d["id"], d["reply"])
                state.mark_replied(d["id"])
                stats["posted"] += 1
            else:
                state.enqueue(d["id"], vid, d["author"], d["text"], d["reply"])
                stats["queued"] += 1
    return stats


def review_queue(cfg: Settings, state: State, approve_all: bool = False) -> int:
    """Interactive approval: [y]es / [n]o / [e]dit / [q]uit."""
    sent = 0
    for item in state.pending():
        print(f"\n@{item['author']}: {item['text']}\n  -> {item['reply']}")
        ans = "y" if approve_all else input("post? [y/n/e/q] ").strip().lower()
        if ans == "q":
            break
        if ans == "e":
            item["reply"] = input("new reply: ").strip() or item["reply"]
            ans = "y"
        if ans == "y":
            youtube.reply(item["comment_id"], item["reply"])
            state.mark_replied(item["comment_id"])
            state.set_queue_status(item["comment_id"], "posted")
            sent += 1
            time.sleep(random.uniform(cfg.reply_min_delay_s, cfg.reply_max_delay_s) if approve_all else 2)
        else:
            state.set_queue_status(item["comment_id"], "rejected")
    return sent
