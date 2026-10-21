"""Video assembly with plain ffmpeg: stock footage (Pexels) or generated Ken-Burns backgrounds, burned-in
captions + on-screen text, voiceover, optional ducked music, final loudness normalisation (-14 LUFS)."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from .config import Settings
from .media import duration, font_path, run
from .script import Script

PALETTES = [((15, 23, 42), (30, 64, 175)), ((24, 24, 27), (190, 24, 93)), ((8, 47, 73), (13, 148, 136)),
            ((39, 24, 8), (217, 119, 6)), ((30, 10, 60), (124, 58, 237))]


# ---------- visuals ----------
def fetch_stock_clip(query: str, dest: Path, cfg: Settings) -> Path | None:
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        return None
    if dest.exists():
        return dest
    try:
        orient = "portrait" if cfg.format == "short" else "landscape"
        r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": key},
                         params={"query": query, "per_page": 5, "orientation": orient}, timeout=30)
        r.raise_for_status()
        for v in r.json().get("videos", []):
            files = [f for f in v["video_files"] if f.get("file_type") == "video/mp4" and f.get("width", 0) >= 1280]
            if files:
                best = min(files, key=lambda f: f["width"])
                data = requests.get(best["link"], timeout=120).content
                dest.write_bytes(data)
                return dest
    except Exception as e:  # noqa: BLE001
        print(f"[video] stock fetch failed for '{query}': {e}")
    return None


def make_background(text: str, idx: int, dest: Path, size: tuple[int, int]) -> Path:
    w, h = size
    top, bot = PALETTES[idx % len(PALETTES)]
    img = Image.new("RGB", size)
    px = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        px.line([(0, y), (w, y)], fill=tuple(int(top[c] + (bot[c] - top[c]) * t) for c in range(3)))
    if text:
        fp = font_path()
        font = ImageFont.truetype(fp, int(h * 0.08)) if fp else ImageFont.load_default()
        wrapped = "\n".join(textwrap.wrap(text, width=18 if w < h else 30))
        px.multiline_text((w / 2, h / 2), wrapped, font=font, fill="white", anchor="mm", align="center",
                          stroke_width=3, stroke_fill="black")
    img.save(dest)
    return dest


# ---------- captions ----------
def _ts(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def write_ass(narration: str, on_screen: str, dur: float, dest: Path, size: tuple[int, int]) -> Path:
    w, h = size
    fs = int(h * 0.055)
    words = narration.split()
    chunks = [" ".join(words[i:i + 4]) for i in range(0, len(words), 4)] or [""]
    total = sum(len(c) for c in chunks) or 1
    lines, t = [], 0.0
    for c in chunks:
        d = dur * len(c) / total
        lines.append(f"Dialogue: 0,{_ts(t)},{_ts(t + d)},Cap,,0,0,0,,{c.upper()}")
        t += d
    if on_screen:
        lines.append(f"Dialogue: 1,{_ts(0.2)},{_ts(min(dur, 3.2))},Top,,0,0,0,,{on_screen}")
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Cap,DejaVu Sans,{fs},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,{int(h * 0.12)},1
Style: Top,DejaVu Sans,{int(fs * 1.1)},&H0000E5FF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,2,8,60,60,{int(h * 0.08)},1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    dest.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return dest


# ---------- assembly ----------
def build_scene(i: int, scene, audio: Path, dur: float, work: Path, cfg: Settings) -> Path:
    w, h = cfg.size
    ass = write_ass(scene.narration, scene.on_screen_text, dur, work / f"scene_{i:02d}.ass", cfg.size)
    out = work / f"scene_{i:02d}.mp4"
    common_tail = ["-map", "0:v", "-map", "1:a", "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
                   "-ac", "2", str(out)]
    sub = f"subtitles={ass.name}"
    clip = fetch_stock_clip(scene.visual_query, work / f"stock_{i:02d}.mp4", cfg)
    if clip:
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps=30,{sub}"
        cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(clip), "-i", str(audio), "-vf", vf] + common_tail
    else:
        bg = make_background(scene.on_screen_text, i, work / f"bg_{i:02d}.png", cfg.size)
        n = max(1, int(dur * 30))
        zoom = "min(zoom+0.0006,1.12)" if i % 2 == 0 else "if(eq(on,1),1.12,max(zoom-0.0006,1.0))"
        vf = (f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={w}x{h}:fps=30,{sub}")
        cmd = ["ffmpeg", "-y", "-i", str(bg), "-i", str(audio), "-vf", vf] + common_tail
    run(cmd, cwd=work)  # cwd so the subtitles filter gets a bare filename (no path escaping issues)
    return out


def assemble(script: Script, narration: list[tuple[Path, float]], out_path: Path, cfg: Settings) -> Path:
    work = out_path.parent / "build"
    work.mkdir(parents=True, exist_ok=True)
    scene_files = [build_scene(i, sc, a, d, work, cfg) for i, (sc, (a, d)) in enumerate(zip(script.scenes, narration))]
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in scene_files))
    joined = work / "joined.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listing.name, "-c", "copy", joined.name], cwd=work)

    music = Path(cfg.music_path) if cfg.music_path and Path(cfg.music_path).exists() else None
    loud = "loudnorm=I=-14:TP=-1.5:LRA=11"
    if music:
        fc = (f"[0:a]asplit[v][sc];[1:a]volume=0.35[m];[m][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];"
              f"[v][duck]amix=inputs=2:duration=first:dropout_transition=0,{loud}[a]")
        run(["ffmpeg", "-y", "-i", str(joined), "-stream_loop", "-1", "-i", str(music), "-filter_complex", fc,
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
             "-movflags", "+faststart", str(out_path)])
    else:
        try:
            run(["ffmpeg", "-y", "-i", str(joined), "-af", loud, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart", str(out_path)])
        except RuntimeError:  # e.g. loudnorm can't measure a near-silent track
            run(["ffmpeg", "-y", "-i", str(joined), "-c", "copy", "-movflags", "+faststart", str(out_path)])
    return out_path


def chapters_from(script: Script, narration) -> str:
    """YouTube chapter timestamps for the description (first must be 0:00, >=3 chapters)."""
    t, lines = 0.0, []
    for sc, (_, d) in zip(script.scenes, narration):
        label = (sc.on_screen_text or sc.narration.split(".")[0])[:45]
        lines.append(f"{int(t // 60)}:{int(t % 60):02d} {label}")
        t += d
    return "\n".join(lines) if len(lines) >= 3 and t >= 180 else ""


def extract_frame(video: Path, at: float, dest: Path):
    run(["ffmpeg", "-y", "-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(dest)])
    return dest


def make_short_from(video: Path, dest: Path, seconds: float = 45.0) -> Path:
    """Vertical 9:16 cut of the opening (hook) for Shorts/Reels/TikTok promotion."""
    seconds = min(seconds, max(5.0, duration(video)))
    run(["ffmpeg", "-y", "-i", str(video), "-t", f"{seconds:.1f}", "-vf",
         "crop=ih*9/16:ih,scale=1080:1920,setsar=1", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dest)])
    return dest
