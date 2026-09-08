# Server Backup

Windows desktop application for backing up a live Ubuntu web server (Nginx, MariaDB, OJS, and configurable extra paths).

**Version 1.4.0**

Primary action: **BACKUP NOW**. Automatic scheduling is **OFF by default**. Both methods use the same backup engine.

This application is independent of Cursor after installation.

## What 1.4.0 changes

BACKUPS NOW write a single logical **master** at `G:\ServerBackups\master\`.

- First successful run is a **FULL master baseline**.
- Later runs are **INCREMENTAL** (NEW / MODIFIED / DELETED / RENAMED / MOVED).
- If nothing changed, the run is **NO_CHANGE** (history only; HEAD is unchanged).
- Master does **not** use keep-5 retention and does **not** rebuild a giant `tar.gz` on every run.
- Existing `G:\ServerBackups\YYYY-MM-DD_HHMMSS\` archives from 1.3.7 are left untouched and are never used as MASTER HEAD.

Objects are SHA-256 content-addressed. Inventory is metadata-first; only change candidates are hashed. OJS private files are streamed as objects and are never copied into `/tmp`.

## Safety

- Never stops Nginx, PHP-FPM, MariaDB, or Docker
- Never reboots the server
- Never modifies website files, databases, or Nginx configuration during backup
- Never deletes an existing 1.3.7 timestamped backup
- Never advances HEAD if transfer, hashing, database dump, integrity verification, or cancellation fails
- Failed, cancelled, and incomplete operations leave the previous HEAD valid

## OJS discovery

`files_dir` is read from each approved site's `config.inc.php`. A missing or invalid `files_dir` is a hard failure. There is no silent fallback to `/var/www/ojs-files`.

Known mappings:

| Application | Private files |
| --- | --- |
| `/var/www/journal.50sea.com` | `/var/lib/ojs-journal50` |
| `/var/www/journal.xdgen.com` | `/var/www/ojs-files` |

Additional valid OJS installations are discovered the same way. Approved website roots are only:

- `/var/www/journal.50sea.com`
- `/var/www/journal.xdgen.com`
- `/var/www/xdgen.com`
- `/var/www/50sea.com`

`/var/www` as a whole is not included. Docker trees and historical migration copies are not included unless you add them under extra directories.

## Database

No binlogs. Each selected database is fingerprinted first (`SHOW TABLE STATUS` + table list). Unchanged databases are skipped. Changed databases are dumped with `mysqldump --single-transaction`. Filesystem objects and database dumps belong to the same generation. A database failure does not advance HEAD.

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
python -m app.main --rebuild-master
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
- `/usr/local/lib/serverbackup/security-audit.sh`

Never `NOPASSWD: ALL`. New 1.4.0 helper modules (`prepare_master.py`, `restore_master.py`) are installed next to those scripts and imported by them. They are not extra sudoers paths.

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
| Master retention | none (no keep-5) |
| Automatic backup | OFF |

The SSH setting is the **path** to a private key file on the Windows PC, or you can enter the Ubuntu password when the app asks. Password logins use Paramiko (Windows OpenSSH cannot type a password). The same password is reused for `sudo` when Ubuntu asks for it. The password is kept in memory only and is never written to config or logs. Restore reuses the in-memory password.

## Backup layout

```
G:\ServerBackups\
  master\
    HEAD
    meta.json
    objects\<ab>\<sha256>
    trees\<generation>.json
    history\<operation-id>.json
    staging\<operation-id>\
  2026-09-07_082000\          (legacy 1.3.7 archive; left untouched)
    server-backup.tar.gz
    backup-info.json
    backup.log
```

HEAD is replaced only after the new tree, objects, and database dumps (if any) verify. A crash during staging leaves the previous HEAD valid.

**DRY RUN** is a metadata-only preview: it connects over SSH, discovers OJS `files_dir`, inventories approved sources, and compares against master **without hashing the live tree or writing HEAD**. A missing master is reported as `NO BASELINE` / `FULL BASELINE PREVIEW`, not as a failure.

**REBUILD MASTER BASELINE** stages a new full generation and replaces HEAD only after verification.

## Restore

Restore requires typing `RESTORE`. You can restore the current master HEAD or a historical generation. Legacy 1.3.7 timestamped archives remain selectable. The Ubuntu helper creates a safety copy where practical and runs `nginx -t` after Nginx restores. **Nginx is never restarted automatically.**

## Tests

```powershell
cd ServerBackup
pip install pytest
pytest tests -v
```

Engine tests do not require PySide6, a G: drive, or the production Ubuntu server.
