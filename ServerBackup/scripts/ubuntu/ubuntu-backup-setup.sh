#!/usr/bin/env bash
# Ubuntu production helper for Server Backup.
# Default is inspect-only. Destructive steps require explicit flags.
# This script does NOT stop Nginx, PHP-FPM, or MariaDB.
set -euo pipefail

DO_CREATE_USER=0
DO_SUDOERS=0
DO_MYSQL_USER=0
INSTALL_SCRIPTS=0
BACKUP_USER="${BACKUP_USER:-serverbackup}"
SSH_USER="${SUDO_USER:-${USER:-zhz}}"

usage() {
  cat <<'EOF'
ubuntu-backup-setup.sh

Inspect and optionally configure the Ubuntu server for Server Backup.

Default: verify only. No sudoers, users, or MariaDB accounts are changed.

Options:
  --install-scripts   Copy prepare/restore scripts to /usr/local/lib/serverbackup
  --create-user       Create a dedicated backup user (serverbackup)
  --sudoers           Install a restricted sudoers rule (NOT ALL=(ALL) NOPASSWD: ALL)
  --mysql-user        Create a local MariaDB backup user (interactive password prompt)
  --ssh-user NAME     Linux user that Windows will SSH as (default: invoking sudo user)
  -h, --help          Show this help

This script will not overwrite sudoers without visudo validation.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-scripts) INSTALL_SCRIPTS=1 ;;
    --create-user) DO_CREATE_USER=1 ;;
    --sudoers) DO_SUDOERS=1 ;;
    --mysql-user) DO_MYSQL_USER=1 ;;
    --ssh-user) SSH_USER="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

echo "=== Server Backup Ubuntu setup (non-destructive by default) ==="

if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  echo "OS: ${PRETTY_NAME:-unknown}"
  if [[ "${ID:-}" != "ubuntu" ]]; then
    echo "WARNING: this script is intended for Ubuntu Server."
  fi
else
  echo "WARNING: /etc/os-release not found"
fi

need() {
  if command -v "$1" >/dev/null 2>&1; then
    echo "OK: $1"
  else
    echo "MISSING: $1"
    return 1
  fi
}

MISSING=0
need sshd || need ssh || true
need tar || MISSING=1
need gzip || MISSING=1
need python3 || MISSING=1
need mysql || echo "WARNING: mysql client missing"
need mysqldump || echo "WARNING: mysqldump missing"
need nginx || echo "WARNING: nginx missing"

echo
echo "=== Path checks (read-only) ==="
for path in \
  /var/www/journal.50sea.com \
  /var/www/journal.xdgen.com \
  /var/www/xdgen.com \
  /var/www/ojs-files \
  /etc/nginx
 do
  if [[ -d "$path" ]]; then
    echo "OK: $path"
  else
    echo "MISSING: $path"
  fi
done

echo
echo "=== /tmp free space ==="
df -h /tmp || true

if [[ "$INSTALL_SCRIPTS" -eq 1 ]]; then
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: --install-scripts requires root." >&2
    exit 1
  fi
  SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  DEST=/usr/local/lib/serverbackup
  mkdir -p "$DEST"
  install -m 0755 "$SRC/prepare-backup.sh" "$DEST/prepare-backup.sh"
  install -m 0755 "$SRC/prepare_backup.py" "$DEST/prepare_backup.py"
  install -m 0755 "$SRC/restore-backup.sh" "$DEST/restore-backup.sh"
  install -m 0755 "$SRC/restore_backup.py" "$DEST/restore_backup.py"
  install -m 0755 "$SRC/security-audit.sh" "$DEST/security-audit.sh"
  install -m 0755 "$SRC/security_audit.py" "$DEST/security_audit.py"
  echo "Installed scripts to $DEST"
fi

if [[ "$DO_CREATE_USER" -eq 1 ]]; then
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: --create-user requires root." >&2
    exit 1
  fi
  if id "$BACKUP_USER" >/dev/null 2>&1; then
    echo "User $BACKUP_USER already exists (left unchanged)."
  else
    useradd --create-home --shell /bin/bash "$BACKUP_USER"
    echo "Created user $BACKUP_USER. Add an SSH public key to ~$BACKUP_USER/.ssh/authorized_keys."
  fi
fi

if [[ "$DO_SUDOERS" -eq 1 ]]; then
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: --sudoers requires root." >&2
    exit 1
  fi
  if ! command -v visudo >/dev/null 2>&1; then
    echo "ERROR: visudo is required to validate sudoers." >&2
    exit 1
  fi
  FILE=/etc/sudoers.d/serverbackup
  if [[ -f "$FILE" ]]; then
    cp -a "$FILE" "${FILE}.bak.$(date +%Y%m%d%H%M%S)"
    echo "Backed up existing $FILE"
  fi
  TMP="$(mktemp)"
  cat >"$TMP" <<EOF
# Restricted Server Backup sudoers. Never use NOPASSWD: ALL.
${SSH_USER} ALL=(root) NOPASSWD: /usr/local/lib/serverbackup/prepare-backup.sh
${SSH_USER} ALL=(root) NOPASSWD: /usr/local/lib/serverbackup/restore-backup.sh
${SSH_USER} ALL=(root) NOPASSWD: /usr/local/lib/serverbackup/security-audit.sh
EOF
  if visudo -c -f "$TMP"; then
    install -m 0440 "$TMP" "$FILE"
    echo "Installed restricted sudoers for $SSH_USER"
  else
    echo "ERROR: sudoers validation failed; existing configuration was not replaced." >&2
    rm -f "$TMP"
    exit 1
  fi
  rm -f "$TMP"
fi

if [[ "$DO_MYSQL_USER" -eq 1 ]]; then
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: --mysql-user requires root." >&2
    exit 1
  fi
  mkdir -p /etc/serverbackup
  if [[ -f /etc/serverbackup/my.cnf ]]; then
    echo "/etc/serverbackup/my.cnf already exists (left unchanged)."
  else
    python3 - <<'PY'
import getpass, os, subprocess, tempfile
pw = getpass.getpass("MariaDB password for serverbackup user: ")
sql = (
    "CREATE USER IF NOT EXISTS 'serverbackup'@'localhost' IDENTIFIED BY %s;\n"
    "GRANT SELECT, SHOW VIEW, TRIGGER, LOCK TABLES, EVENT, PROCESS ON *.* "
    "TO 'serverbackup'@'localhost';\nFLUSH PRIVILEGES;\n"
)
# mysql CLI cannot take a bound parameter; write an escaped SQL file with 0600 perms.
import re
if re.search(r"[\x00\n\r]", pw):
    raise SystemExit("Password contains unsupported characters.")
escaped = pw.replace("\\", "\\\\").replace("'", "\\'")
text = (
    "CREATE USER IF NOT EXISTS 'serverbackup'@'localhost' IDENTIFIED BY '" + escaped + "';\n"
    "GRANT SELECT, SHOW VIEW, TRIGGER, LOCK TABLES, EVENT, PROCESS ON *.* "
    "TO 'serverbackup'@'localhost';\nFLUSH PRIVILEGES;\n"
)
fd, path = tempfile.mkstemp(prefix="serverbackup-sql-")
os.fchmod(fd, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    handle.write(text)
try:
    subprocess.run(["mysql", "--batch"], check=True, stdin=open(path, encoding="utf-8"))
    os.makedirs("/etc/serverbackup", exist_ok=True)
    cnf = "/etc/serverbackup/my.cnf"
    with open(cnf, "w", encoding="utf-8") as handle:
        handle.write("[client]\nuser=serverbackup\npassword=" + pw + "\n")
    os.chmod(cnf, 0o600)
    print("Wrote /etc/serverbackup/my.cnf (mode 600). Password is not printed.")
finally:
    os.remove(path)
PY
  fi
fi

echo
echo "Setup checks finished. Missing required tools: $MISSING"
echo "No production websites, databases, or Nginx configuration were modified."
exit "$MISSING"
