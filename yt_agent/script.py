"""Retention-engineered script: hook -> stakes -> payoff loops -> CTA, split into scenes with visual cues."""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import Settings
from .llm import LLM
from .research import Idea


@dataclass
class Scene:
    narration: str
    visual_query: str  # stock-footage search phrase
    on_screen_text: str = ""


@dataclass
class Script:
    title: str
    title_options: list
    description: str
    tags: list
    thumbnail_texts: list  # <=4 words each
    scenes: list = field(default_factory=list)
    chapters: list = field(default_factory=list)

    @property
    def narration(self) -> str:
        return " ".join(s.narration for s in self.scenes)


SYSTEM = """You are an elite YouTube scriptwriter. Rules:
- Open with a hook that creates a curiosity gap within 5 seconds. No 'Hey guys', no channel intro.
- Re-hook every ~60s (pattern interrupt, open loop, payoff). Concrete numbers, examples, stories.
- Spoken English, short sentences, zero filler. Be accurate; never invent statistics or quotes.
- Title and thumbnail text must be honest: they promise only what the video delivers.
- End with ONE natural call to action (subscribe/next video), not a begging list."""


def write_script(cfg: Settings, llm: LLM, idea: Idea) -> Script:
    words = int(cfg.video_minutes * 150)
    n_scenes = max(3, int(cfg.video_minutes * 60 / 12))
    prompt = f"""Idea: {idea.title}\nAngle: {idea.angle}\nHook seed: {idea.hook}\nKeywords: {idea.keywords}
Channel voice: {cfg.channel_voice}\nTarget length: ~{words} spoken words in ~{n_scenes} scenes
({'vertical Short, under 60s, ~130 words' if cfg.format == 'short' else 'long-form'}).

JSON schema:
{{"title": str<=65, "title_options": [3 alternatives], "description": str (first 2 lines = hook + keywords,
then timestamps placeholder, then short links section),
"tags": [<=15 str], "thumbnail_texts": [3 options, max 4 words each, high-contrast emotional/curiosity],
"scenes": [{{"narration": str (2-4 sentences), "visual_query": str (3-5 words, concrete, filmable),
"on_screen_text": str (<=6 words or empty)}}]}}"""
    fallback = {
        "title": idea.title,
        "title_options": [idea.title],
        "description": f"{idea.hook}\n\n{idea.angle}\n\n#{'#'.join(idea.keywords[:3]) if idea.keywords else ''}",
        "tags": idea.keywords,
        "thumbnail_texts": ["WATCH THIS FIRST", "DON'T MISS THIS", "THE REAL TRUTH"],
        "scenes": [
            {"narration": idea.hook, "visual_query": "technology abstract", "on_screen_text": ""},
            {"narration": f"{idea.angle}. Here is why it matters, and how you can use it today.",
             "visual_query": "person working laptop", "on_screen_text": "Why it matters"},
            {"narration": "That's the whole idea. If this helped, subscribe and watch the next video.",
             "visual_query": "city timelapse", "on_screen_text": "Subscribe"},
        ],
    }
    d = llm.json(SYSTEM, prompt, fallback, max_tokens=8000)
    scenes = [Scene(s["narration"], s.get("visual_query", "abstract background"), s.get("on_screen_text", ""))
              for s in d["scenes"]]
    return Script(
        title=d["title"][:100], title_options=d.get("title_options", []), description=d["description"],
        tags=d.get("tags", [])[:15], thumbnail_texts=d.get("thumbnail_texts") or ["WATCH THIS"], scenes=scenes,
    )
