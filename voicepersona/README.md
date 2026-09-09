# VoxPersona

Web app for families who want to **keep a loved one’s voice and talking style** — then talk with that same accent later.

Runs on **cPanel shared hosting** (PHP + static UI). Accounts require **admin approval** and a **monthly subscription**.

## Accounts & billing

1. Visitor **creates an account** (pending).
2. Request is emailed to admin and appears in **Admin accounts**.
3. Admin can **Allow**, **Decline**, or **Restrict**.
4. **Allow** starts a **1-month** subscription.
5. Near expiry, a **reminder email** is sent (cPanel cron).
6. After login + active plan, the voice studio opens (same interface as before).

Default admin (change in `api/config.php` on the server):

- Email: `admin@voxpersona.local`
- Password: `Admin@123456`

## Local demo

```bash
# API
cd voicepersona
php -S 127.0.0.1:8790 -t api api/router.php

# UI
cd frontend
npm install
npm run dev
```

Open http://localhost:5174 → create account → log in as admin → Allow the user → user can enter the studio.

## Deploy to cPanel

```bash
cd voicepersona
bash scripts/build-cpanel.sh
```

Upload **contents** of `deploy/dist/` into `public_html`.  
Edit `api/config.php` (price, admin email, mail from, cron key).

### Cron for renewal reminders (cPanel → Cron Jobs)

Once daily:

```bash
curl -s "https://YOUR-DOMAIN.com/api/cron/reminders?key=YOUR_CRON_KEY"
```

## Studio modes (after login)

| Mode | What happens |
|------|----------------|
| Family conversation | Only **Start listening** — language, accent, style, laugh/mood auto-captured |
| Talk with program | Hold-to-talk; Discussion AI replies; voice stored |
| Talk with [Name] | Chat in that person’s accent & style |

Use **Chrome** for best automatic speech recognition during family listening.

### Stronger discussion AI (optional)

In `api/config.php` set an OpenAI-compatible key (`llm_api_key`, `llm_base_url`, `llm_model`).  
Without a key, built-in Discussion AI still holds a real conversation (not Eliza-only).

## Tech

- React static frontend
- PHP 8 API + SQLite users/sessions
- Discussion AI (+ optional LLM); Eliza only as fallback
- Auto speech analysis (language/accent/style)
- Browser speech for demo playback
