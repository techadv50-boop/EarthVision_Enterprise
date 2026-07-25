# VoxPersona

Web app for families who want to **keep a loved one’s voice and talking style** — then talk with that same accent later.

Built to run on **cPanel shared hosting** (PHP API + static web UI). No VPS required.

## Who it is for

Older people may not log in themselves. Typical use:

1. **Son/daughter + elder sit together**  
   Headphones/mic on the elder. They talk naturally. The program records the elder’s voice, accent, and manner.

2. **Elder talks with the program**  
   Any topic. The program replies (Eliza AI). Purpose: keep capturing the real voice.

3. **Many people**  
   Save Irfan, Amma, Abu, … Later choose who you want to talk with — replies follow that person’s style.

## Quick start (local)

### PHP API (cPanel-compatible)

```bash
cd voicepersona
php -S 127.0.0.1:8790 -t api api/router.php
```

### Frontend

```bash
cd voicepersona/frontend
npm install
npm run dev
```

Open http://localhost:5174

## Deploy to cPanel shared domain

```bash
cd voicepersona
bash scripts/build-cpanel.sh
```

Upload **contents** of `deploy/dist/` into `public_html` (or a subdomain).  
Details: [deploy/README-CPANEL.md](deploy/README-CPANEL.md)

## Modes in the interface

| Mode | What happens |
|------|----------------|
| Family conversation | Continuous listening on elder mic while family talks |
| Talk with program | Hold-to-talk; program replies; voice is stored |
| Talk with [Name] | Chat/speak in that person’s captured accent & style |

## Tech

- Frontend: React + Vite (static build for cPanel)
- Backend: PHP 8 (works on shared hosting)
- AI: Eliza built-in (no external API key)
- Speech playback: browser speech synthesis (good demo)

Optional Python backend under `backend/` remains for experimentation; **cPanel deploy uses PHP only**.
