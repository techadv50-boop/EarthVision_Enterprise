"""Print the in-memory SSH password for OpenSSH SSH_ASKPASS. Never logs it."""

from __future__ import annotations

import os
import sys


def write_password() -> int:
    sys.stdout.write(os.environ.get("SERVERBACKUP_ASKPASS", ""))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(write_password())
