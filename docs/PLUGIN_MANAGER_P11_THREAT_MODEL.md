# Stage P1.1 Threat Model (Plugin Manager)

## Assets

- Host Shell integrity (auth, map, DB, legacy tools, 148-tool catalog)
- Plugin registry + immutable artifacts on `tool_packs` volume
- Production secrets / DB credentials in API process

## Adversaries

- Malicious or compromised admin session uploading packs
- PR author attempting to bypass core protection via env vars / policy edits
- Concurrent workers racing registry / install
- Zip bombs, path traversal, symlink plants

## Controls (implemented)

| Threat | Control |
|--------|---------|
| Core bypass via `CORE_RELEASE=approved` | Rejected; require auditable `CORE_RELEASE_APPROVAL` + `tools/core_releases/<id>.json` bound to `base_sha` |
| Missing git base | Fail closed (exit 2) |
| Weaken protection in same PR | Self-protect; approval must exist on comparison base once checker is live |
| `source_path` RCE / file read | Removed from admin API; opaque staging IDs only |
| Zip traversal / bomb | Entry count, decompressed size, traversal + symlink rejects, staging TTL |
| Install wrong bytes | Digest-bound install (`expected_digest` must match validated staging) |
| Env mutation races | `verify_pack_at` — no `EV_ARTIFACTS_ROOT` mutation |
| Registry clobber across workers | `fcntl` lock + atomic rename RMW |
| Plugin code in API process | Disabled; static `ui/synthetic.json` only |
| Permissions as fake sandbox | Documented as declarations only |
| Arbitrary remote JS | Static host maps only; secure FE contract documented, not enabled |

## Residual risk / P2

- No production publisher keys or live overlay yet
- No reviewed worker/container for nontrivial plugin Python
- Admin upload still trusted for *installing inactive* artifacts (activate remains explicit)
- Frontend independent bundles not yet available under the secure contract

## Production

No production deployment in P1.1.
