# Authorized Administrator Password Reset (E1.9A)

Ordinary **Deploy SATEYE** runs must **not** reset admin credentials.

## Defaults

| Path | Behavior |
|------|----------|
| `RESET_ADMIN_PASSWORD` in `deploy_sateye_live.sh` | Default **`0`** (disabled) |
| Deploy workflow `admin_reset_confirm` | Empty → reset disabled |
| Deploy workflow | Reset only when `admin_reset_confirm=reset-admin` **and** `confirm=deploy` |

## Authorized maintenance procedure

1. Owner explicitly authorizes a password reset (separate from Host Shell / pack activation).
2. Run Deploy SATEYE with:
   - `confirm` = `deploy`
   - `admin_reset_confirm` = `reset-admin`
3. Or, on the live host with documented dual confirm (ops-only), export:
   ```bash
   export RESET_ADMIN_PASSWORD=1
   export ADMIN_EMAIL_RESET=admin@xdgen.com
   # ADMIN_PASSWORD_RESET from a secrets manager — never commit
   ```
   then run the maintenance-only path of `deploy_sateye_live.sh` / sync helper under change control.
4. Record who authorized the reset, when, and the `.env` fingerprint (size+sha256 only).

## Verification that ordinary deploy cannot reset

- Workflow without `admin_reset_confirm=reset-admin` sets `RESET_ADMIN_PASSWORD=0`.
- Script skips sync when `RESET_ADMIN_PASSWORD!=1`.
- Unit tests assert default-off behavior.
