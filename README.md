# YouTube AI Agent

An end-to-end agent that researches what's working in your niche, writes the script, records a cleaned-up
AI voiceover, assembles the video, designs A/B thumbnails, uploads/schedules it, drafts replies to comments,
and generates platform-native promotion.

```
research ─▶ script ─▶ voice ─▶ video ─▶ thumbnails ─▶ [you review] ─▶ upload ─▶ promote ─▶ engage
```

| Stage | Module | What it does |
|---|---|---|
| Research | `research.py` | YouTube search + competitor uploads → **outlier score** (views ÷ subs), views/hour, Google Trends rising queries → Claude extracts patterns and returns ranked, *original* ideas |
| Script | `script.py` | Hook in 5s, re-hooks every ~60s, scene list with stock-footage queries, 3 title + 3 thumbnail-text options, description, tags |
| Voice | `voice.py` | edge-tts (free) or ElevenLabs → high-pass, denoise, compression, silence trim; final -14 LUFS mastering; optional auto-ducked music |
| Video | `video.py` | Pexels footage (or Ken-Burns backgrounds), burned-in captions + on-screen text, chapters, 9:16 teaser cut |
| Thumbnails | `thumbnail.py` | 3 variants, outlined text ≤4 words, vignette/saturation, size + contrast self-check |
| Upload | `youtube.py` | Resumable upload with retries, scheduling, thumbnail, AI-content disclosure flag |
| Comments | `engagement.py` | Classify → draft in your voice → **approval queue** (or auto-post), spam/link filters, caps, random delays |
| Promotion | `social.py` | X thread, Reddit, LinkedIn, IG/TikTok, Community post copy; auto-posts to Telegram/Discord/X if keys set |

## Setup
```bash
pip install -r requirements.txt        # needs ffmpeg on PATH
cp .env.example .env                   # add keys (only ANTHROPIC_API_KEY is essential)
edit config.yaml                       # niche, voice, privacy, approval mode
```
YouTube upload/comments: create a Google Cloud project → enable **YouTube Data API v3** → OAuth client (Desktop) →
save as `client_secret.json`. First upload opens a browser for consent.

## Use
```bash
python -m yt_agent research            # ideas + outlier videos (JSON)
python -m yt_agent make                # build a video to workspace/runs/<id>/ and stop for review
python -m yt_agent publish workspace/runs/<id> [--at 2026-10-21T14:00:00Z]
python -m yt_agent engage              # draft replies into the queue
python -m yt_agent engage --review     # approve / edit / reject in the terminal
python -m yt_agent daemon              # daily make + hourly engage (or use cron)
```
With no API keys everything still runs in placeholder mode (`pytest` does this) so you can test the plumbing.

## Things you need to know
- **Unaudited API projects upload as private only.** Apply for the YouTube API compliance audit before expecting public uploads.
- **Quota:** 10k units/day; an upload costs 1,600, a reply 50, a search 100.
- **Policy:** YouTube demotes/removes mass-produced, repetitive, low-effort content and spammy automation. Defaults here are
  deliberately conservative: human review before publish, private uploads, reply approval queue, AI-content disclosure.
  Loosen them (`require_approval: false`, `auto_reply: true`) only once output quality has earned it.
- **Originality:** research copies *patterns*, not videos. Add your own angle, examples, on-camera or screen footage
  as the channel grows - that is what makes videos perform, not volume.
- **Not possible via API:** pinning/hearting comments, Studio's title/thumbnail "Test & Compare". Those stay manual.
- **Social:** Reddit, TikTok, Instagram and LinkedIn are left as drafts on purpose (bot-posted promo gets accounts banned).
- Footage/music must be licensed: Pexels footage is free to use; supply royalty-free music via `music_path`.

## Extending
Swap in image generation for thumbnails (replace `_base()`), add your own screen recordings as a scene source in
`video.build_scene`, wire `youtube.stats()` into `research.py` to learn from your own winners, or add
a YouTube Analytics retention report to feed back into the script prompt.
