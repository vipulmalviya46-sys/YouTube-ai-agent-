"""Orchestrator: make() builds everything to a review-ready folder; publish() uploads + promotes."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from pathlib import Path

from . import research, social, thumbnail, video, voice, youtube
from .config import Settings
from .llm import LLM
from .research import Idea
from .script import Scene, Script, write_script
from .state import State


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def _load_script(d: dict) -> Script:
    return Script(**{**d, "scenes": [Scene(**s) for s in d["scenes"]]})


def make(cfg: Settings, llm: LLM, state: State, idea: Idea | None = None) -> Path:
    if idea is None:
        _, ideas = research.research(cfg, llm, state)
        idea = ideas[0]
    run_dir = cfg.work_dir / "runs" / f"{time.strftime('%Y%m%d-%H%M')}-{_slug(idea.title)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"[make] idea: {idea.title}")

    script = write_script(cfg, llm, idea)
    narr = voice.narrate_scenes(script.scenes, run_dir / "audio", cfg)
    out = video.assemble(script, narr, run_dir / "final.mp4", cfg)
    chapters = video.chapters_from(script, narr)
    if chapters:
        script.description = script.description.replace("[timestamps]", chapters)
        if chapters not in script.description:
            script.description += "\n\nChapters:\n" + chapters

    # clean base for thumbnails: stock clip frame if we have one, else the generated background (no captions)
    build = run_dir / "build"
    if (build / "stock_00.mp4").exists():
        frame = video.extract_frame(build / "stock_00.mp4", 1.0, run_dir / "frame.jpg")
    else:
        frame = build / "bg_00.png"
    thumbs = thumbnail.make_thumbnails(script.thumbnail_texts, frame, run_dir / "thumbnails")

    meta = {
        "status": "ready", "idea": asdict(idea), "script": asdict(script), "video": str(out),
        "thumbnails": [str(t) for t in thumbs], "thumb_checks": [thumbnail.check(t) for t in thumbs],
        "duration_s": round(sum(d for _, d in narr), 1),
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    state.mark_idea_used(idea.title)
    print(f"[make] ready for review: {run_dir}")
    return run_dir


def publish(cfg: Settings, llm: LLM, state: State, run_dir: Path, publish_at: str | None = None,
            promote: bool = True) -> str:
    meta = json.loads((run_dir / "meta.json").read_text())
    script = _load_script(meta["script"])
    desc = script.description
    if cfg.declare_synthetic_media:
        desc += "\n\nThis video uses AI-generated narration and visuals."
    vid = youtube.upload_video(Path(meta["video"]), script.title, desc, script.tags, cfg.category_id, cfg.privacy,
                               publish_at, cfg.declare_synthetic_media, cfg.language)
    try:
        youtube.set_thumbnail(vid, Path(meta["thumbnails"][0]))  # needs a verified channel
    except Exception as e:  # noqa: BLE001
        print(f"[publish] thumbnail not set (channel verified?): {e}")
    state.add_video(vid, run_dir, script.title, {"publish_at": publish_at})
    meta.update(status="published", video_id=vid)
    if promote:
        try:
            short = video.make_short_from(Path(meta["video"]), run_dir / "teaser_9x16.mp4")
            meta["teaser"] = str(short)
            meta["promo"] = social.promote(cfg, llm, script, vid, run_dir, post=cfg.privacy == "public" and not publish_at)
        except Exception as e:  # noqa: BLE001
            print(f"[publish] promotion step failed: {e}")
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"[publish] https://youtu.be/{vid}")
    return vid


def make_and_maybe_publish(cfg: Settings, llm: LLM, state: State) -> Path:
    run_dir = make(cfg, llm, state)
    if cfg.require_approval:
        print(f"[run] approval required -> review {run_dir}/final.mp4, then: python -m yt_agent publish {run_dir}")
    else:
        publish(cfg, llm, state, run_dir)
    return run_dir
