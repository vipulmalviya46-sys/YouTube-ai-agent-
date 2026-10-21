from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    niche: str = "AI tools for creators"
    language: str = "en"
    region: str = "US"
    channel_voice: str = "Energetic, clear, witty. Short sentences."
    competitor_channel_ids: list = field(default_factory=list)
    format: str = "long"
    video_minutes: float = 8
    research_days: int = 14
    tts_provider: str = "edge"
    tts_voice: str = "en-US-AndrewNeural"
    tts_rate: str = "+0%"
    elevenlabs_voice_id: str = ""
    music_path: str = ""
    privacy: str = "private"
    require_approval: bool = True
    declare_synthetic_media: bool = True
    category_id: str = "28"
    auto_reply: bool = False
    max_replies_per_run: int = 15
    reply_min_delay_s: int = 20
    reply_max_delay_s: int = 90
    daemon: dict = field(default_factory=lambda: {"make_at": "09:00", "engage_every_minutes": 60})
    work_dir: Path = ROOT / "workspace"

    @property
    def size(self) -> tuple[int, int]:
        return (1080, 1920) if self.format == "short" else (1920, 1080)

    @property
    def db_path(self) -> Path:
        return self.work_dir / "state.sqlite"


def load(path: str | Path | None = None) -> Settings:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    path = Path(path or os.getenv("YT_AGENT_CONFIG", ROOT / "config.yaml"))
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    known = {f.name for f in fields(Settings)}
    s = Settings(**{k: v for k, v in (data or {}).items() if k in known})
    s.work_dir = Path(s.work_dir)
    s.work_dir.mkdir(parents=True, exist_ok=True)
    return s
