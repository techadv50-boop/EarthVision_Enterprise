# Production Tool Pack Signing Key Provisioning (B-KEYS / E1.9A)

**This stage never generates, displays, stores, or commits production private keys.**

## Separation of identities

| Identity | Where | Use |
|----------|-------|-----|
| `preview-dev` | `tools/publishers/approved_publishers.preview.json` | Preview + local/CI only |
| Image default | `approved_publishers.image_default.json` (empty) | Fail-closed bake-in |
| Production publisher | Volume `/data/tool_packs/publishers/approved_publishers.json` | Live install/activate only |

## Ops procedure (offline / secrets manager)

1. On an air-gapped or secrets-manager workstation (**not** this repo commit path), generate an Ed25519 keypair.
2. Store the **private** key only in the team secrets manager (Hardware/HSM preferred). Never write it into git, Docker images, CI logs, or chat.
3. Place **only** the public key into a production allowlist file derived from  
   `deployment/production/approved_publishers.production.TEMPLATE.json`:
   - `id`: unique production publisher id (not `preview-dev`)
   - `environment`: `production`
   - `enabled`: `true`
   - `public_key`: base64url raw public key
4. Install that file on the live `tool_packs` volume as  
   `/data/tool_packs/publishers/approved_publishers.json`.
5. Ensure live compose sets:
   - `EV_PACK_PUBLISHERS=/data/tool_packs/publishers/approved_publishers.json`
   - `EV_PACK_TRUST_PROFILE=production`
6. Sign production artifacts with the private key offline; transfer only signed bundles + `SIGNATURE.json`.
7. Rotate by enabling a new publisher and disabling the old in the volume allowlist (immutable artifact dirs still apply).

## Fail-closed behavior

With `EV_PACK_TRUST_PROFILE=production`:

- Empty allowlist → install/activate rejected
- `preview-dev` / `environment=preview` entries ignored/rejected
- Missing publishers file → rejected
