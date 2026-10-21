from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import config, engagement, pipeline, research, social
from .llm import LLM
from .state import State


def main(argv=None):
    ap = argparse.ArgumentParser(prog="yt_agent", description="YouTube AI agent")
    ap.add_argument("--config", help="path to config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("research", help="find outlier videos + ranked ideas")
    sub.add_parser("make", help="research -> script -> voice -> video -> thumbnails (stops for review)")
    p = sub.add_parser("publish", help="upload a reviewed run + thumbnail + promo")
    p.add_argument("run_dir")
    p.add_argument("--at", help="schedule, RFC3339 UTC e.g. 2026-10-21T14:00:00Z")
    p = sub.add_parser("promote", help="regenerate social copy for a published run")
    p.add_argument("run_dir")
    e = sub.add_parser("engage", help="draft (and optionally post) comment replies")
    e.add_argument("--review", action="store_true", help="interactively approve the queue")
    e.add_argument("--approve-all", action="store_true")
    sub.add_parser("run", help="make (+ publish if require_approval is false)")
    sub.add_parser("daemon", help="run daily creation + hourly engagement forever")
    a = ap.parse_args(argv)

    cfg = config.load(a.config)
    llm, state = LLM(), State(cfg.db_path)
    if not llm.online:
        print("[warn] no GEMINI/OPENAI/ANTHROPIC key set - running in offline/placeholder mode")
    else:
        print(f"[llm] using {llm.provider} ({llm.model})")

    if a.cmd == "research":
        signals, ideas = research.research(cfg, llm, state)
        print(json.dumps({"signals": [research.to_dict(s) for s in signals[:10]],
                          "ideas": [research.to_dict(i) for i in ideas]}, indent=2))
    elif a.cmd == "make":
        pipeline.make(cfg, llm, state)
    elif a.cmd == "run":
        pipeline.make_and_maybe_publish(cfg, llm, state)
    elif a.cmd == "publish":
        pipeline.publish(cfg, llm, state, Path(a.run_dir), a.at)
    elif a.cmd == "promote":
        meta = json.loads((Path(a.run_dir) / "meta.json").read_text())
        s = pipeline._load_script(meta["script"])
        print(social.promote(cfg, llm, s, meta["video_id"], Path(a.run_dir)))
    elif a.cmd == "engage":
        if a.review or a.approve_all:
            print(f"posted {engagement.review_queue(cfg, state, a.approve_all)} replies")
        else:
            print(engagement.run_engagement(cfg, llm, state))
    elif a.cmd == "daemon":
        daemon(cfg, llm, state)


def daemon(cfg, llm, state):
    """Simple scheduler loop. For production use cron/systemd/GitHub Actions instead and call `run` / `engage`."""
    last_make_day, last_engage = None, 0.0
    every = cfg.daemon.get("engage_every_minutes", 60) * 60
    while True:
        now = time.localtime()
        if time.strftime("%H:%M", now) >= cfg.daemon.get("make_at", "09:00") and last_make_day != now.tm_yday:
            last_make_day = now.tm_yday
            try:
                pipeline.make_and_maybe_publish(cfg, llm, state)
            except Exception as ex:  # noqa: BLE001
                print(f"[daemon] make failed: {ex}")
        if time.time() - last_engage > every:
            last_engage = time.time()
            try:
                print("[daemon] engage:", engagement.run_engagement(cfg, llm, state))
            except Exception as ex:  # noqa: BLE001
                print(f"[daemon] engage failed: {ex}")
        time.sleep(30)


if __name__ == "__main__":
    main()
