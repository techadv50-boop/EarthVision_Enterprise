from __future__ import annotations

import json
from pathlib import Path

import aiofiles

from .models import Persona, utc_now

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
PERSONAS_DIR = DATA_DIR / "personas"
SAMPLES_DIR = DATA_DIR / "samples"


def ensure_dirs() -> None:
    PERSONAS_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)


def persona_path(persona_id: str) -> Path:
    return PERSONAS_DIR / f"{persona_id}.json"


def sample_dir(persona_id: str) -> Path:
    path = SAMPLES_DIR / persona_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_personas() -> list[Persona]:
    ensure_dirs()
    personas: list[Persona] = []
    for path in sorted(PERSONAS_DIR.glob("*.json")):
        personas.append(Persona.model_validate_json(path.read_text(encoding="utf-8")))
    return personas


def get_persona(persona_id: str) -> Persona | None:
    path = persona_path(persona_id)
    if not path.exists():
        return None
    return Persona.model_validate_json(path.read_text(encoding="utf-8"))


def save_persona(persona: Persona) -> Persona:
    ensure_dirs()
    persona.updated_at = utc_now()
    path = persona_path(persona.id)
    path.write_text(persona.model_dump_json(indent=2), encoding="utf-8")
    return persona


def delete_persona(persona_id: str) -> bool:
    path = persona_path(persona_id)
    if not path.exists():
        return False
    path.unlink()
    samples = SAMPLES_DIR / persona_id
    if samples.exists():
        for file in samples.iterdir():
            file.unlink(missing_ok=True)
        samples.rmdir()
    return True


async def write_sample_bytes(persona_id: str, filename: str, data: bytes) -> Path:
    ensure_dirs()
    dest = sample_dir(persona_id) / filename
    async with aiofiles.open(dest, "wb") as handle:
        await handle.write(data)
    return dest


def sample_file_path(persona_id: str, filename: str) -> Path:
    return sample_dir(persona_id) / filename


def dump_debug(persona: Persona) -> dict:
    return json.loads(persona.model_dump_json())
