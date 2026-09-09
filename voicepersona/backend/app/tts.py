"""Optional cloud TTS / voice-clone hooks. Browser speech is used by default."""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from . import storage
from .models import Persona


async def maybe_synthesize(persona: Persona, text: str) -> str | None:
    provider = (os.getenv("VOX_TTS_PROVIDER") or "").lower().strip()
    if not provider or provider in {"none", "browser"}:
        return None

    if provider == "elevenlabs":
        return await _elevenlabs(persona, text)
    if provider == "openai":
        return await _openai_tts(persona, text)
    return None


async def _elevenlabs(persona: Persona, text: str) -> str | None:
    api_key = os.getenv("VOX_ELEVENLABS_API_KEY")
    voice_id = persona.voice_clone_id or os.getenv("VOX_ELEVENLABS_VOICE_ID")
    if not api_key or not voice_id:
        return None

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            url,
            headers={
                "xi-api-key": api_key,
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
            },
            json={"text": text, "model_id": "eleven_monolingual_v1"},
        )
        response.raise_for_status()
        filename = f"tts_{persona.id}_{abs(hash(text)) % 10_000_000}.mp3"
        path = await storage.write_sample_bytes(persona.id, filename, response.content)
        return f"/api/personas/{persona.id}/samples/{path.name}/audio"


async def _openai_tts(persona: Persona, text: str) -> str | None:
    api_key = os.getenv("VOX_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    voice = persona.voice_clone_id or os.getenv("VOX_OPENAI_VOICE") or "alloy"
    base_url = (os.getenv("VOX_LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{base_url}/audio/speech",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-4o-mini-tts", "voice": voice, "input": text},
        )
        response.raise_for_status()
        filename = f"tts_{persona.id}_{abs(hash(text)) % 10_000_000}.mp3"
        path = await storage.write_sample_bytes(persona.id, filename, response.content)
        return f"/api/personas/{persona.id}/samples/{path.name}/audio"


def local_audio_path(persona_id: str, filename: str) -> Path:
    return storage.sample_file_path(persona_id, filename)
