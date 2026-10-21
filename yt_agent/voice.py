"""Voiceover: TTS (edge-tts free / ElevenLabs) + broadcast-style cleanup (denoise, de-click, compress, trim silence)."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import requests

from .config import Settings
from .media import duration, run


def _edge(text: str, out: Path, cfg: Settings):
    import edge_tts

    asyncio.run(edge_tts.Communicate(text, cfg.tts_voice, rate=cfg.tts_rate).save(str(out)))


def _eleven(text: str, out: Path, cfg: Settings):
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{cfg.elevenlabs_voice_id}",
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        json={"text": text, "model_id": "eleven_multilingual_v2",
              "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.3}},
        timeout=120,
    )
    r.raise_for_status()
    out.write_bytes(r.content)


def _silent(text: str, out: Path):
    """Offline fallback: silence of roughly speaking length so timing/captions still work."""
    secs = max(2.0, len(text.split()) / 2.6)
    # faint noise rather than digital silence: loudnorm yields NaN on pure silence
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anoisesrc=a=0.03:r=44100", "-t", f"{secs:.2f}",
         "-c:a", "libmp3lame", str(out)])


def synthesize(text: str, out: Path, cfg: Settings) -> Path:
    raw = out.with_suffix(".raw.mp3")
    try:
        if cfg.tts_provider == "elevenlabs" and os.getenv("ELEVENLABS_API_KEY") and cfg.elevenlabs_voice_id:
            _eleven(text, raw, cfg)
        else:
            _edge(text, raw, cfg)
    except Exception as e:  # noqa: BLE001
        print(f"[voice] TTS unavailable ({type(e).__name__}); using silent placeholder")
        _silent(text, raw)
    enhance(raw, out)
    raw.unlink(missing_ok=True)
    return out


def enhance(src: Path, dst: Path):
    """Voice polish chain. Final loudness normalisation happens once on the full mix (video.py)."""
    af = (
        "highpass=f=80,afftdn=nf=-28,"
        "silenceremove=start_periods=1:start_threshold=-50dB:stop_periods=1:stop_duration=0.6:stop_threshold=-50dB,"
        "acompressor=threshold=-20dB:ratio=3:attack=5:release=80,"
        "apad=pad_dur=0.25"  # breathing room between scenes
    )
    try:
        run(["ffmpeg", "-y", "-i", str(src), "-af", af, "-ar", "44100", "-ac", "1", str(dst)])
    except RuntimeError:
        run(["ffmpeg", "-y", "-i", str(src), "-ar", "44100", "-ac", "1", str(dst)])


def narrate_scenes(scenes, out_dir: Path, cfg: Settings) -> list[tuple[Path, float]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    res = []
    for i, sc in enumerate(scenes):
        p = synthesize(sc.narration, out_dir / f"scene_{i:02d}.mp3", cfg)
        res.append((p, duration(p)))
    return res
