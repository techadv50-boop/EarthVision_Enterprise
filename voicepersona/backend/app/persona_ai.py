from __future__ import annotations

import os
import re
from typing import Iterable

import httpx

from . import eliza
from .models import ChatMessage, MoodTag, Persona, VoiceSample


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            out.append(cleaned)
    return out


def build_style_guide(persona: Persona, mood: MoodTag | None = None) -> list[str]:
    traits = persona.traits
    notes: list[str] = []

    if traits.accent or any(s.accent for s in persona.samples):
        accent = traits.accent or next((s.accent for s in persona.samples if s.accent), "")
        if accent:
            notes.append(f"Speak with a {accent} accent flavor in word choice and rhythm.")

    style = traits.talking_style or next(
        (s.talking_style for s in persona.samples if s.talking_style), ""
    )
    if style:
        notes.append(f"Talking style: {style}.")

    if traits.laugh_style:
        notes.append(f"When amused, laugh like this: {traits.laugh_style}.")
    if traits.sadness_style:
        notes.append(f"When sad, sound like this: {traits.sadness_style}.")
    if traits.vocabulary_notes:
        notes.append(f"Vocabulary: {traits.vocabulary_notes}.")
    if traits.filler_words:
        notes.append("Natural fillers: " + ", ".join(traits.filler_words) + ".")
    if traits.catchphrases:
        notes.append("Occasionally use catchphrases: " + "; ".join(traits.catchphrases) + ".")

    sample_moods = _unique(
        [m.value for s in persona.samples for m in s.moods] + [m.value for m in traits.moods_observed]
    )
    if sample_moods:
        notes.append("Observed moods in training: " + ", ".join(sample_moods) + ".")

    transcripts = [s.transcript.strip() for s in persona.samples if s.transcript.strip()]
    if transcripts:
        preview = " | ".join(transcripts[:4])
        notes.append(f"Mirror phrasing from these samples: {preview}")

    if mood:
        notes.append(f"Current reply mood target: {mood.value}.")
        if mood == MoodTag.laughing and traits.laugh_style:
            notes.append("Include a short laugh cue matching the laugh style.")
        if mood == MoodTag.sad and traits.sadness_style:
            notes.append("Soften pacing and lean into the sadness style.")

    if not notes:
        notes.append("Reply warmly and conversationally in first person as this persona.")
    return notes


def _apply_style_transforms(text: str, persona: Persona, mood: MoodTag | None) -> str:
    out = text.strip()
    traits = persona.traits

    # Soften clinical Eliza tone toward conversational first person.
    replacements = [
        (r"\bPlease tell me more\b", "Tell me more, yeah?"),
        (r"\bVery interesting\b", "That's interesting"),
        (r"\bI see\b", "Mm, I hear you"),
        (r"\bWhy do you ask\b", "Why you asking"),
        (r"\bHow does that make you feel\b", "How's that sitting with you"),
    ]
    for pattern, repl in replacements:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)

    if traits.filler_words and len(out.split()) > 6:
        filler = traits.filler_words[0]
        if filler.lower() not in out.lower():
            out = f"{filler.capitalize()}, {out[0].lower() + out[1:]}" if out else out

    if mood == MoodTag.laughing:
        laugh = traits.laugh_style or "haha"
        if laugh.lower() not in out.lower():
            out = f"{out} {laugh}"
    elif mood == MoodTag.sad:
        cue = traits.sadness_style or "soft and quiet"
        if "…" not in out and "..." not in out:
            out = out.rstrip(".!") + "…"
        out = f"{out} ({cue})"

    if traits.catchphrases and len(out) < 180:
        phrase = traits.catchphrases[0]
        if phrase.lower() not in out.lower() and hash(out) % 3 == 0:
            out = f"{out} {phrase}"

    # Accent flavoring is intentionally light-touch to avoid caricature.
    accent = (traits.accent or "").lower()
    if "southern" in accent or "texas" in accent:
        out = re.sub(r"\byou all\b", "y'all", out, flags=re.IGNORECASE)
    if "british" in accent or "uk" in accent:
        out = out.replace("favorite", "favourite").replace("color", "colour")

    return out


def _collect_training_blob(samples: list[VoiceSample]) -> str:
    chunks: list[str] = []
    for sample in samples:
        bits = [f"[{sample.kind.value}]"]
        if sample.accent:
            bits.append(f"accent={sample.accent}")
        if sample.talking_style:
            bits.append(f"style={sample.talking_style}")
        if sample.moods:
            bits.append("moods=" + ",".join(m.value for m in sample.moods))
        if sample.transcript:
            bits.append(sample.transcript)
        if sample.notes:
            bits.append(sample.notes)
        chunks.append(" ".join(bits))
    return "\n".join(chunks[:12])


async def generate_reply(
    persona: Persona,
    message: str,
    history: list[ChatMessage] | None = None,
    mood: MoodTag | None = None,
) -> tuple[str, str, list[str]]:
    style_notes = build_style_guide(persona, mood)
    engine = (persona.ai_engine or "eliza").lower().strip()

    if engine in {"openai", "llm", "compat"}:
        reply = await _llm_reply(persona, message, history or [], style_notes, mood)
        return reply, "openai", style_notes

    raw = eliza.respond(message)
    styled = _apply_style_transforms(raw, persona, mood)
    return styled, "eliza", style_notes


async def _llm_reply(
    persona: Persona,
    message: str,
    history: list[ChatMessage],
    style_notes: list[str],
    mood: MoodTag | None,
) -> str:
    api_key = os.getenv("VOX_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        # Fall back gracefully so the product still works without keys.
        raw = eliza.respond(message)
        return _apply_style_transforms(raw, persona, mood)

    base_url = (os.getenv("VOX_LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("VOX_LLM_MODEL") or "gpt-4o-mini"
    training = _collect_training_blob(persona.samples)

    system = (
        f"You are embodying a real person named {persona.name}. "
        f"Description: {persona.description or 'No description'}. "
        "Answer every user query in their voice and talking style. "
        "Stay in character. Keep replies concise and natural.\n"
        "Style rules:\n- " + "\n- ".join(style_notes)
    )
    if training:
        system += f"\n\nTraining samples:\n{training}"

    messages = [{"role": "system", "content": system}]
    for item in history[-12:]:
        role = "assistant" if item.role == "assistant" else "user"
        messages.append({"role": role, "content": item.content})
    messages.append({"role": "user", "content": message})

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": messages, "temperature": 0.8},
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
