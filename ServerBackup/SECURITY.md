# Server Backup security

Version 1.4.0

## Principles

1. Protect production data first.
2. Never mark a backup SUCCESS until it is verified.
3. Never store Ubuntu passwords, MariaDB passwords, or private keys in source code.
4. Never log passwords, private keys, or secret tokens.
5. Never grant unrestricted `sudo ALL=(ALL) NOPASSWD: ALL`.
6. Never execute user input as a shell string.
7. Never silently overwrite production files or delete successful backups.

## Secrets

| Secret | Where it lives | What the Windows app stores |
| --- | --- | --- |
| SSH private key | File chosen by the administrator (typically `%USERPROFILE%\.ssh\`) | Path only |
| Ubuntu account password | Typed in the GUI when connecting; held in memory only | Nothing (never saved) |
| MariaDB password | `/etc/serverbackup/my.cnf` on Ubuntu, mode `600` | Nothing |

The GUI must never display private key contents.

## SSH

Key-only backups use the system OpenSSH client (`ssh` / `scp`) in BatchMode with an argv list. Password logins use Paramiko so Windows can type the Ubuntu password without OpenSSH ASKPASS. Remote sudo uses `sudo -A` with a short-lived 0600 askpass file over SFTP; helper JSON stays on stdin and the password is never placed on argv or in the JSON payload. Restricted sudoers remains optional for scheduled key-only backups.

Remote work is limited to allowlisted actions handled by:

- `/usr/local/lib/serverbackup/prepare-backup.sh`
- `/usr/local/lib/serverbackup/restore-backup.sh`
- `/usr/local/lib/serverbackup/security-audit.sh` (read-only audit by default; token hash files only under `/etc/serverbackup/`)

JSON payloads are passed on stdin. Unix paths are validated (absolute, no `..`, no shell metacharacters).

## Sudoers

The setup script, when explicitly invoked with `--sudoers`, installs a visudo-validated drop-in. It is backed up if a previous file exists. Syntax is checked before replacement.

## Backup atomicity

Master objects are written under `G:\ServerBackups\master\staging\<operation>\` and copied into `objects\` as SHA-256 content-addressed blobs. `trees\<generation>.json` and `history\` are written first. **HEAD is last.**

The previous HEAD remains valid if transfer, hashing, database dump, integrity verification, cancellation, or a crash occurs during staging.

Legacy 1.3.7 timestamped folders under `G:\ServerBackups\YYYY-MM-DD_HHMMSS\` are never used as HEAD and are never deleted by 1.4.0 retention (master has no keep-5).

## Restore

Restore is a separate confirmed flow. The operator must type `RESTORE`. Safety copies are created on Ubuntu under `/var/backups/serverbackup-safety/` where practical. Nginx is validated with `nginx -t` and is **not** reloaded or restarted by this application.

## Logging

Logs are written to `C:\ServerBackup\Logs\backup-YYYY-MM-DD.log` (configurable). A redacting formatter strips password/token/private-key patterns.

## Three-layer on-demand audit

Security scanning is **not continuous**. **SECURITY CHECK** collects a scoped snapshot (configured website/OJS/Nginx/SSH/php/letsencrypt trees plus host metadata), stores it on the Windows PC, compares it with the previous trusted snapshot, and writes a report.

Workflow: AUDIT → SNAPSHOT → COMPARE → CLASSIFY → REPORT. Applying host firewall or `sshd` changes is **not** done automatically. Rollback restores only application-managed security state (token hashes under `/etc/serverbackup/` and the local trusted pointer), not production websites.

Modes: LOW, **BALANCED** (default), HIGH, CRITICAL. Higher modes hash more files but still skip cache trees and never walk `/`.

Credential rotation generates a cryptographically secure application token, shows it once, stores only a hash, and keeps the previous hash until verification so the administrator is not locked out.

## Threat notes

- Mapped network drives named `G:` may be unavailable to Task Scheduler when nobody is logged on. Prefer a local disk.
- Password-authenticated **BACKUP NOW** runs inside the GUI so the Ubuntu password never goes to disk. Keep the window open until the backup finishes. Key-only scheduled backups can still run from Task Scheduler.
- This tool cannot protect backups stored only on the production server. Copies live on the Windows disk.
