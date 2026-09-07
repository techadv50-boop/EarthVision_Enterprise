# Server Backup

Windows desktop application for backing up a live Ubuntu web server (Nginx, MariaDB, OJS, and configurable extra paths).

**Version 1.3.4**

Primary action: **BACKUP NOW**. Automatic scheduling is **OFF by default**. Both methods use the same backup engine.

This application is independent of Cursor after installation.

## Safety

- Never stops Nginx, PHP-FPM, or MariaDB
- Never reboots the server
- Never modifies website files, databases, or Nginx configuration during backup
- Never deletes an existing successful backup because a new backup started
- Marks SUCCESS only after transfer, archive integrity, and SHA-256 complete
- Failed, cancelled, and incomplete backups do not count toward retention

## Server security (on-demand)

A dedicated **SERVER SECURITY** section audits the Ubuntu host when you click **SECURITY CHECK**. It does not run in the background and does not change the backup/restore workflow.

Three layers:

1. Entry — firewall, SSH, listening ports, brute-force signals  
2. Access — users, sudoers, authorized-key fingerprints  
3. Integrity — scoped metadata/hashes for websites, OJS files, Nginx, and selected configs  

Default mode is **BALANCED** (audit only). The checker does not copy production trees, does not hash the entire disk, and does not stop Nginx, PHP-FPM, or MariaDB. Detected changes are classified; nothing is quarantined or overwritten automatically.

Credential rotation applies only to the application security token. MariaDB, OJS, website, PHP, SMTP, and API secrets are never rotated by this app.

## Requirements (Windows backup PC)

- Windows 10/11
- OpenSSH Client (`ssh`, `scp`) for key-only login. Password login is built into `ServerBackup.exe`.
- Backup disk, typically `G:\` with destination `G:\ServerBackups`
- Python 3.12+ only if running from source (not required for `ServerBackup.exe`)

## Layout

```
ServerBackup/
├── app/                 # Python application (GUI + engine)
├── scripts/ubuntu/      # Run on the Ubuntu server (you run these)
├── scripts/windows/     # Optional Task Scheduler helpers
├── tests/
├── config/default.json
├── README.md
└── SECURITY.md
```

## Run from source

```powershell
cd ServerBackup
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m app.main
```

CLI (same engine as the GUI):

```powershell
python -m app.main --backup
python -m app.main --dry-run
python -m app.main --test-connection
python -m app.main --discover-databases
python -m app.main --cancel
python -m app.main --security-check

```

## Build ServerBackup.exe

On a Windows machine (or the Windows GitHub Actions job):

```powershell
cd ServerBackup
pip install -r requirements.txt
pyinstaller --noconfirm serverbackup.spec
```

The packaged app is `dist\ServerBackup.exe`. End users do not need Python.

## Ubuntu server setup (you run this)

This Cloud/development environment must **not** be used to change production automatically. Copy `scripts/ubuntu/` to the server and inspect first.

```bash
sudo bash ubuntu-backup-setup.sh
sudo bash ubuntu-backup-setup.sh --install-scripts --sudoers --ssh-user zhzh
```

`--create-user` and `--mysql-user` are optional. The sudoers rule allows **only**:

- `/usr/local/lib/serverbackup/prepare-backup.sh`
- `/usr/local/lib/serverbackup/restore-backup.sh`

Never `NOPASSWD: ALL`.

Place an SSH public key for the Windows backup PC in the Ubuntu account's `authorized_keys`. MariaDB credentials stay on Ubuntu in `/etc/serverbackup/my.cnf` (mode 600).

## Windows configuration

On first launch the app **prompts you to select the backup drive**. You can also click **CHOOSE BACKUP DRIVE** or **EDIT SETTINGS** on the dashboard. Dashboard status cards are read-only.

Settings are stored in `%APPDATA%\ServerBackup\config.json`.

Defaults:

| Setting | Default |
| --- | --- |
| Server | `192.168.18.18` |
| SSH user | `zhzh` |
| Destination | `G:\ServerBackups` |
| Logs | `C:\ServerBackup\Logs` |
| Retention | 5 successful backups |
| Automatic backup | OFF |

The SSH setting is the **path** to a private key file on the Windows PC, or you can enter the Ubuntu password when the app asks. Password logins use Paramiko (Windows OpenSSH cannot type a password). The same password is reused for `sudo` when Ubuntu asks for it. The password is kept in memory only and is never written to config or logs.

## Backup layout

```
G:\ServerBackups\
  .incomplete_2026-09-07_082000\    (temporary; deleted on failure)
  2026-09-07_082000\
    server-backup.tar.gz
    backup-info.json
    backup.log
```

Only the finalized timestamp directory is a successful backup. Retention deletes the oldest **successful** directory only after a new backup is verified.

## Restore

Restore requires typing `RESTORE`. The Ubuntu helper creates a safety copy where practical and runs `nginx -t` after Nginx restores. **Nginx is never restarted automatically.**

## Tests

```powershell
cd ServerBackup
pip install pytest
pytest tests -v
```

Engine tests do not require PySide6, a G: drive, or the production Ubuntu server.
