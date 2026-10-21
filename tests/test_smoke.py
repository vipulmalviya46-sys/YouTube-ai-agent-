"""Offline smoke test: no API keys, no network. Needs ffmpeg."""
import json
import shutil

import pytest

from yt_agent import config, pipeline
from yt_agent.llm import LLM
from yt_agent.state import State
from yt_agent.media import duration


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")
def test_make_offline(tmp_path, monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "YOUTUBE_API_KEY", "PEXELS_API_KEY", "ELEVENLABS_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    cfg = config.load()
    cfg.work_dir = tmp_path
    cfg.tts_provider = "none"  # skip network TTS -> silent placeholder
    monkeypatch.setattr("yt_agent.voice._edge", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    state = State(cfg.db_path)
    run_dir = pipeline.make(cfg, LLM(), state)
    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["status"] == "ready"
    assert duration(run_dir / "final.mp4") > 3
    assert len(meta["thumbnails"]) == 3 and all(c["size_ok"] and c["bytes_ok"] for c in meta["thumb_checks"])
