from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid4().hex


class MoodTag(str, Enum):
    neutral = "neutral"
    happy = "happy"
    sad = "sad"
    laughing = "laughing"
    angry = "angry"
    excited = "excited"
    calm = "calm"
    anxious = "anxious"
    affectionate = "affectionate"
    sarcastic = "sarcastic"


class SampleKind(str, Enum):
    speech = "speech"
    laughing = "laughing"
    sadness = "sadness"
    accent = "accent"
    style = "style"
    other = "other"


class VoiceSample(BaseModel):
    id: str = Field(default_factory=new_id)
    filename: str
    kind: SampleKind = SampleKind.speech
    transcript: str = ""
    accent: str = ""
    talking_style: str = ""
    moods: list[MoodTag] = Field(default_factory=list)
    notes: str = ""
    duration_ms: int | None = None
    created_at: str = Field(default_factory=utc_now)


class PersonaTraits(BaseModel):
    accent: str = ""
    talking_style: str = ""
    vocabulary_notes: str = ""
    laugh_style: str = ""
    sadness_style: str = ""
    filler_words: list[str] = Field(default_factory=list)
    catchphrases: list[str] = Field(default_factory=list)
    moods_observed: list[MoodTag] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class Persona(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    description: str = ""
    traits: PersonaTraits = Field(default_factory=PersonaTraits)
    samples: list[VoiceSample] = Field(default_factory=list)
    ai_engine: str = "eliza"
    voice_clone_id: str | None = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class PersonaCreate(BaseModel):
    name: str
    description: str = ""
    traits: PersonaTraits | None = None
    ai_engine: str = "eliza"


class PersonaUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    traits: PersonaTraits | None = None
    ai_engine: str | None = None
    voice_clone_id: str | None = None


class SampleMeta(BaseModel):
    kind: SampleKind = SampleKind.speech
    transcript: str = ""
    accent: str = ""
    talking_style: str = ""
    moods: list[MoodTag] = Field(default_factory=list)
    notes: str = ""
    duration_ms: int | None = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)
    mood: MoodTag | None = None
    speak: bool = True


class ChatResponse(BaseModel):
    reply: str
    engine: str
    style_notes: list[str] = Field(default_factory=list)
    audio_url: str | None = None
