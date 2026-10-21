# Tool Pack Security Boundaries (E1.5)

## Execution privilege

Signed/verified Python Tool Pack plugins are loaded **into the FastAPI/uvicorn process** via `importlib`.

**Implication:** A pack plugin runs with the **same OS privileges** as the backend worker (filesystem access available to that user, network egress policy of the host, access to whatever the Host SDK exposes).

Integrity checks (SHA256SUMS + pin digest) reduce *tamper-after-build* risk. They do **not** provide:

- Process isolation / sandboxing
- seccomp / gVisor / container-per-pack
- Capability drop beyond the backend service account

## Controls in E1.5

| Control | Present |
|---------|---------|
| Allowlisted artifact directory only | Yes |
| Digest verification before load | Yes |
| Immutable artifact directories (no overwrite) | Yes |
| Atomic validated pin writes + `.bak` recovery | Yes |
| Admin/dev-only promote scripts (not public API) | Yes |
| Host SDK port (no direct DB credentials in pack) | Yes (convention) |

## Future hardening (not E1.5)

- Cosign/GPG signatures on artifacts
- Separate worker pool or subprocess for untrusted packs
- Explicit capability tokens on HostImageryPort
- Read-only mount of artifact volume

## Frontend modules

Backend-only packs (E1 `true_color`) avoid remote JS execution. Future remote UI modules must be same-origin, CSP-limited, and must not ship a second React/Leaflet copy (see `TOOL_PACK_FRONTEND_LOADING.md`).
