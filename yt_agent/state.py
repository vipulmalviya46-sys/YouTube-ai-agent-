"""Tiny SQLite store: what we already replied to, what we published, and the reply approval queue."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


class State:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS replied (comment_id TEXT PRIMARY KEY, ts REAL);
            CREATE TABLE IF NOT EXISTS queue (
                comment_id TEXT PRIMARY KEY, video_id TEXT, author TEXT, text TEXT,
                reply TEXT, status TEXT DEFAULT 'pending', ts REAL);
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY, run_dir TEXT, title TEXT, ts REAL, meta TEXT);
            CREATE TABLE IF NOT EXISTS used_ideas (title TEXT PRIMARY KEY, ts REAL);
            """
        )

    # replies
    def already_replied(self, cid: str) -> bool:
        return self.db.execute("SELECT 1 FROM replied WHERE comment_id=?", (cid,)).fetchone() is not None

    def mark_replied(self, cid: str):
        self.db.execute("INSERT OR REPLACE INTO replied VALUES (?,?)", (cid, time.time()))
        self.db.commit()

    def enqueue(self, cid, video_id, author, text, reply):
        self.db.execute(
            "INSERT OR IGNORE INTO queue (comment_id, video_id, author, text, reply, ts) VALUES (?,?,?,?,?,?)",
            (cid, video_id, author, text, reply, time.time()),
        )
        self.db.commit()

    def pending(self):
        cur = self.db.execute("SELECT comment_id, video_id, author, text, reply FROM queue WHERE status='pending'")
        return [dict(zip(("comment_id", "video_id", "author", "text", "reply"), r)) for r in cur]

    def set_queue_status(self, cid, status):
        self.db.execute("UPDATE queue SET status=? WHERE comment_id=?", (status, cid))
        self.db.commit()

    # videos / ideas
    def add_video(self, video_id, run_dir, title, meta=None):
        self.db.execute(
            "INSERT OR REPLACE INTO videos VALUES (?,?,?,?,?)",
            (video_id, str(run_dir), title, time.time(), json.dumps(meta or {})),
        )
        self.db.commit()

    def recent_video_ids(self, limit=10):
        return [r[0] for r in self.db.execute("SELECT video_id FROM videos ORDER BY ts DESC LIMIT ?", (limit,))]

    def idea_used(self, title: str) -> bool:
        return self.db.execute("SELECT 1 FROM used_ideas WHERE title=?", (title,)).fetchone() is not None

    def mark_idea_used(self, title: str):
        self.db.execute("INSERT OR REPLACE INTO used_ideas VALUES (?,?)", (title, time.time()))
        self.db.commit()
