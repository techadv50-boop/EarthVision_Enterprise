from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import storage, tts
from .models import (
    ChatRequest,
    ChatResponse,
    MoodTag,
    Persona,
    PersonaCreate,
    PersonaTraits,
    PersonaUpdate,
    SampleKind,
    SampleMeta,
    VoiceSample,
    new_id,
    utc_now,
)
from .persona_ai import generate_reply

app = FastAPI(
    title="VoxPersona API",
    description="Capture a person's voice & talking style; reply with a background AI in that persona.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

storage.ensure_dirs()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "voxpersona", "ai_default": "eliza"}


@app.get("/api/engines")
def list_engines() -> dict:
    return {
        "engines": [
            {
                "id": "eliza",
                "name": "Eliza",
                "description": "Classic pattern chatbot with persona style transforms. Works offline.",
            },
            {
                "id": "openai",
                "name": "OpenAI-compatible LLM",
                "description": "Uses VOX_LLM_API_KEY (+ optional VOX_LLM_BASE_URL / VOX_LLM_MODEL).",
            },
        ]
    }


@app.get("/api/personas", response_model=list[Persona])
def api_list_personas() -> list[Persona]:
    return storage.list_personas()


@app.post("/api/personas", response_model=Persona)
def api_create_persona(payload: PersonaCreate) -> Persona:
    persona = Persona(
        name=payload.name.strip(),
        description=payload.description.strip(),
        traits=payload.traits or PersonaTraits(),
        ai_engine=payload.ai_engine or "eliza",
    )
    if not persona.name:
        raise HTTPException(400, "Name is required")
    return storage.save_persona(persona)


@app.get("/api/personas/{persona_id}", response_model=Persona)
def api_get_persona(persona_id: str) -> Persona:
    persona = storage.get_persona(persona_id)
    if not persona:
        raise HTTPException(404, "Persona not found")
    return persona


@app.patch("/api/personas/{persona_id}", response_model=Persona)
def api_update_persona(persona_id: str, payload: PersonaUpdate) -> Persona:
    persona = storage.get_persona(persona_id)
    if not persona:
        raise HTTPException(404, "Persona not found")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(persona, key, value)
    return storage.save_persona(persona)


@app.delete("/api/personas/{persona_id}")
def api_delete_persona(persona_id: str) -> dict:
    if not storage.delete_persona(persona_id):
        raise HTTPException(404, "Persona not found")
    return {"deleted": True}


@app.post("/api/personas/{persona_id}/samples", response_model=VoiceSample)
async def api_add_sample(
    persona_id: str,
    file: UploadFile = File(...),
    meta: str = Form("{}"),
) -> VoiceSample:
    persona = storage.get_persona(persona_id)
    if not persona:
        raise HTTPException(404, "Persona not found")

    try:
        meta_obj = SampleMeta.model_validate(json.loads(meta or "{}"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Invalid sample meta: {exc}") from exc

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty audio upload")

    ext = Path(file.filename or "sample.webm").suffix or ".webm"
    filename = f"{new_id()}{ext}"
    await storage.write_sample_bytes(persona_id, filename, raw)

    sample = VoiceSample(
        filename=filename,
        kind=meta_obj.kind,
        transcript=meta_obj.transcript,
        accent=meta_obj.accent,
        talking_style=meta_obj.talking_style,
        moods=meta_obj.moods,
        notes=meta_obj.notes,
        duration_ms=meta_obj.duration_ms,
    )
    persona.samples.append(sample)

    # Fold annotations into living traits.
    if sample.accent and not persona.traits.accent:
        persona.traits.accent = sample.accent
    if sample.talking_style and not persona.traits.talking_style:
        persona.traits.talking_style = sample.talking_style
    for mood in sample.moods:
        if mood not in persona.traits.moods_observed:
            persona.traits.moods_observed.append(mood)
    if sample.kind == SampleKind.laughing and sample.notes and not persona.traits.laugh_style:
        persona.traits.laugh_style = sample.notes
    if sample.kind == SampleKind.sadness and sample.notes and not persona.traits.sadness_style:
        persona.traits.sadness_style = sample.notes

    storage.save_persona(persona)
    return sample


@app.get("/api/personas/{persona_id}/samples/{filename}/audio")
def api_sample_audio(persona_id: str, filename: str) -> FileResponse:
    path = storage.sample_file_path(persona_id, filename)
    if not path.exists():
        raise HTTPException(404, "Audio not found")
    return FileResponse(path)


@app.delete("/api/personas/{persona_id}/samples/{sample_id}")
def api_delete_sample(persona_id: str, sample_id: str) -> Persona:
    persona = storage.get_persona(persona_id)
    if not persona:
        raise HTTPException(404, "Persona not found")
    match = next((s for s in persona.samples if s.id == sample_id), None)
    if not match:
        raise HTTPException(404, "Sample not found")
    path = storage.sample_file_path(persona_id, match.filename)
    path.unlink(missing_ok=True)
    persona.samples = [s for s in persona.samples if s.id != sample_id]
    return storage.save_persona(persona)


@app.post("/api/personas/{persona_id}/chat", response_model=ChatResponse)
async def api_chat(persona_id: str, payload: ChatRequest) -> ChatResponse:
    persona = storage.get_persona(persona_id)
    if not persona:
        raise HTTPException(404, "Persona not found")
    if not payload.message.strip():
        raise HTTPException(400, "Message is required")

    reply, engine, style_notes = await generate_reply(
        persona,
        payload.message,
        payload.history,
        payload.mood,
    )

    audio_url = None
    if payload.speak:
        audio_url = await tts.maybe_synthesize(persona, reply)

    return ChatResponse(
        reply=reply,
        engine=engine,
        style_notes=style_notes,
        audio_url=audio_url,
    )


@app.get("/api/moods")
def api_moods() -> dict:
    return {"moods": [m.value for m in MoodTag]}


# Optional: serve built frontend if present.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
