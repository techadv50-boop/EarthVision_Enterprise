# Deploy VoxPersona on cPanel (shared hosting)

PHP + static files. Includes **account signup**, **admin approval**, **monthly subscription**, and **renewal reminder emails**.

## Upload

```bash
cd voicepersona
bash scripts/build-cpanel.sh
```

Upload the **contents** of `deploy/dist/` into `public_html` (or a subdomain folder).

```
public_html/
  index.html
  assets/
  .htaccess
  api/          (PHP API + config.php)
  data/         (must be writable)
```

Set `data/` (and subfolders) to **755** or **775** so SQLite and audio uploads work.

## Configure

Edit `api/config.php` on the server:

- `admin_email` / `admin_password` — first-run admin account
- `subscription_price` / `subscription_currency` — monthly plan shown to users
- `mail_from` — use an email on your domain so cPanel mail() works
- `cron_key` — secret for the reminder cron URL
- `app_url` — your public site URL

Default admin after first visit:

- `admin@voxpersona.local` / `Admin@123456`  
  **Change this immediately.**

## Cron (renewal reminder emails)

cPanel → **Cron Jobs** → once per day:

```bash
curl -s "https://YOUR-DOMAIN.com/api/cron/reminders?key=YOUR_CRON_KEY"
```

Users within `reminder_days_before` (default 5 days) of expiry receive a renewal email.

## Admin workflow

1. User creates account → status **pending** (also emailed to admin).
2. Admin logs in → **Admin accounts**.
3. **Allow** → activates account + 30-day subscription.
4. **Decline** / **Restrict** → blocks access.
5. **Renew month** → extends subscription another month.

After Allow, the user logs in and sees the full VoxPersona studio.
