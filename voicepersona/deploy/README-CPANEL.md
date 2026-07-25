# Deploy VoxPersona on cPanel (shared hosting)

This app is built for **cPanel shared hosting** (PHP + static files). No VPS required.

## What you upload

After running the build script, upload everything inside `voicepersona/deploy/dist/` into your domain’s `public_html/` (or a subdomain folder).

Expected layout on the server:

```
public_html/
  index.html
  assets/
  .htaccess
  api/
    index.php
    bootstrap.php
    eliza.php
    persona_ai.php
    .htaccess
  data/
    personas/
    samples/
```

## cPanel steps

1. In cPanel → **File Manager**, open `public_html` (or your subdomain root).
2. Upload the zip of `deploy/dist` and extract it (or upload via FTP).
3. Set permissions:
   - `data/`, `data/personas/`, `data/samples/` → **755** (or 775 if uploads fail)
4. Make sure **Apache mod_rewrite** is enabled (normal on cPanel).
5. Visit `https://your-domain.com/`

## Local build (before upload)

```bash
cd voicepersona
bash scripts/build-cpanel.sh
```

Upload the contents of `voicepersona/deploy/dist/`.

## How families use it

1. Add a person (e.g. **Irfan**).
2. **Family conversation** — son/daughter sits with the elder; mic/headphones on the elder; press Start listening.
3. **Talk with program** — elder holds to talk on any topic; program replies and stores the voice.
4. Later choose **Irfan** (or any other person) → **Talk with them** — replies follow that person’s accent/style.

## Notes

- Demo voice playback uses the browser’s built-in speech (good demo, not studio-grade cloning).
- Many people can be stored; each person keeps their own voice clips and style.
- For stronger future voice cloning on shared hosting, you can later plug a paid TTS API; the capture workflow stays the same.
