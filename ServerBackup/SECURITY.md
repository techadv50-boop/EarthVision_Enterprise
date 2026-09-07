# Server Backup security

Version 1.0.0

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
| Ubuntu account password | Not used (key authentication) | Nothing |
| MariaDB password | `/etc/serverbackup/my.cnf` on Ubuntu, mode `600` | Nothing |

The GUI must never display private key contents.

## SSH

Backups use the system OpenSSH client (`ssh` / `scp`) in BatchMode with an argv list.

Remote work is limited to allowlisted actions handled by:

- `/usr/local/lib/serverbackup/prepare-backup.sh`
- `/usr/local/lib/serverbackup/restore-backup.sh`

JSON payloads are passed on stdin. Unix paths are validated (absolute, no `..`, no shell metacharacters).

## Sudoers

The setup script, when explicitly invoked with `--sudoers`, installs a visudo-validated drop-in. It is backed up if a previous file exists. Syntax is checked before replacement.

## Backup atomicity

Incomplete data is written to `G:\ServerBackups\.incomplete_YYYY-MM-DD_HHMMSS\`. That directory is renamed only after:

1. Transfer completed
2. Archive members exist
3. Archive integrity (tar)
4. SHA-256
5. `backup-info.json` written with `status: SUCCESS`

Failure or cancel deletes **only** the incomplete directory. Existing successful backups are left untouched. Retention runs only after success.

## Restore

Restore is a separate confirmed flow. The operator must type `RESTORE`. Safety copies are created on Ubuntu under `/var/backups/serverbackup-safety/` where practical. Nginx is validated with `nginx -t` and is **not** reloaded or restarted by this application.

## Logging

Logs are written to `C:\ServerBackup\Logs\backup-YYYY-MM-DD.log` (configurable). A redacting formatter strips password/token/private-key patterns.

## Threat notes

- Mapped network drives named `G:` may be unavailable to Task Scheduler when nobody is logged on. Prefer a local disk.
- Closing the GUI does not stop a backup: BACKUP NOW starts a detached process using the same CLI engine.
- This tool cannot protect backups stored only on the production server. Copies live on the Windows disk.
