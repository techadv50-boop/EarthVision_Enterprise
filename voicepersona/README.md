# VoxPersona

Voice & talking-style capture studio with a background AI agent that replies in the same persona.

## What it does

1. **Capture** — Record or upload a person’s voice samples.
2. **Annotate** — Tag accent, talking style, laugh, sadness, moods, and other speech traits.
3. **Feed** — Build a living persona profile from those samples and notes.
4. **Reply** — Chat with a background AI (Eliza by default, optional OpenAI-compatible LLM) that answers in that person’s style.
5. **Speak** — Play replies with browser speech synthesis (hooks ready for ElevenLabs / OpenAI voice clone APIs).

## Quick start

### Backend

```bash
cd voicepersona/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8790
```

API docs: http://localhost:8790/docs

### Frontend

```bash
cd voicepersona/frontend
npm install
npm run dev
```

App: http://localhost:5174

## AI backends

| Engine | Config | Notes |
|--------|--------|-------|
| `eliza` (default) | none | Classic pattern chatbot + persona style transform |
| `openai` | `VOX_LLM_API_KEY`, optional `VOX_LLM_BASE_URL`, `VOX_LLM_MODEL` | Any OpenAI-compatible API (OpenAI, Groq, Ollama proxy, etc.) |

Optional voice clone TTS:

- `VOX_TTS_PROVIDER=elevenlabs` + `VOX_ELEVENLABS_API_KEY`
- `VOX_TTS_PROVIDER=openai` + `VOX_LLM_API_KEY`

## Project layout

```
voicepersona/
├── backend/          # FastAPI persona store + AI agent
├── frontend/         # React capture + chat studio
└── data/             # Local persona profiles & audio samples
```

This package is standalone software (not part of EarthVision). You can move the `voicepersona/` folder into its own repository when ready.
