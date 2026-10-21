"""LLM wrapper with three interchangeable providers: Anthropic (Claude), Google Gemini, OpenAI.

Provider choice: LLM_PROVIDER=anthropic|gemini|openai, otherwise auto-detected from whichever key looks valid.
Gemini and OpenAI are called over plain HTTPS (requests) so nothing extra needs installing.
With no usable key it runs 'offline' and callers use their own fallbacks, so the pipeline can be smoke-tested.
"""
from __future__ import annotations

import json
import os
import re
import time

import requests


def _detect() -> str | None:
    forced = os.getenv("LLM_PROVIDER", "").strip().lower()
    if forced in ("anthropic", "gemini", "openai"):
        return forced
    a = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if a.startswith("sk-ant-api"):  # 'sk-ant-usr-...' and others are not API keys
        return "anthropic"
    if os.getenv("GEMINI_API_KEY", "").strip():
        return "gemini"
    if os.getenv("OPENAI_API_KEY", "").strip():
        return "openai"
    return "anthropic" if a else None


class LLM:
    def __init__(self, model: str | None = None):
        self.provider = _detect()
        self.client = None
        if self.provider == "anthropic":
            import anthropic

            self.model = model or os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
            self.client = anthropic.Anthropic()
        elif self.provider == "gemini":
            self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        elif self.provider == "openai":
            self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        else:
            self.model = ""

    @property
    def online(self) -> bool:
        return self.provider is not None

    # ---- providers ----
    def _post(self, url: str, **kw) -> dict:
        for attempt in range(4):  # free tiers rate-limit: back off and retry
            r = requests.post(url, timeout=120, **kw)
            if r.status_code in (429, 500, 503) and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            if not r.ok:
                raise RuntimeError(f"{self.provider} error {r.status_code}: {r.text[:300]}")
            return r.json()
        raise RuntimeError("unreachable")

    def complete(self, system: str, prompt: str, max_tokens: int = 4000) -> str:
        if self.provider == "anthropic":
            msg = self.client.messages.create(
                model=self.model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        if self.provider == "gemini":
            data = self._post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"].strip()},
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": max(max_tokens, 8192)},
                },
            )
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        if self.provider == "openai":
            data = self._post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY'].strip()}"},
                json={"model": self.model, "max_tokens": max_tokens,
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
            )
            return data["choices"][0]["message"]["content"]
        raise RuntimeError("LLM offline")

    def json(self, system: str, prompt: str, fallback, max_tokens: int = 4000):
        """Ask for JSON; on any failure (offline, bad key, bad JSON) return `fallback`."""
        if not self.online:
            return fallback
        try:
            raw = self.complete(system + "\nReply with ONLY valid JSON, no prose, no code fences.", prompt, max_tokens)
            raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
            data = json.loads(raw)
            if isinstance(fallback, list) and isinstance(data, dict):  # models sometimes wrap: {"ideas": [...]}
                data = next((v for v in data.values() if isinstance(v, list)), fallback)
            return data
        except Exception as e:  # noqa: BLE001
            print(f"[llm:{self.provider}] call failed, using fallback: {e}")
            return fallback
