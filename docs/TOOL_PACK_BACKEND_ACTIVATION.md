# Backend Tool Pack Activation (E0/E1)

## Requirements

- No unsafe in-place Python hot-reload (`importlib.reload` on live modules).
- All uvicorn workers must activate the **same** approved tool version.
- Invalid / tampered artifacts must be rejected.
- Rollback must target a real artifact **or** the verified builtin fallback.

## Mechanism

### 1. Runtime pin (shared source of truth)

File: `tools/runtime_pins.json` (repo / mounted volume in preview).

```json
{
  "true_color": {
    "mode": "pack",
    "version": "1.0.0",
    "digest": "sha256:…",
    "updated_at": "…"
  }
}
```

`mode` is `pack` or `builtin`.

All workers read this file from a shared filesystem path. Consistency = same pin file content.

### 2. Versioned import (safe)

Pack code is loaded from:

`tools/artifacts/true_color/<version>/backend/plugin.py`

via `importlib.util.spec_from_file_location` with a **unique module name**:

`ev_pack_true_color_1_0_0`

- Switching pins loads a **different** module name; old modules are left unused (not reloaded).
- Cache key: `(tool_id, version, digest)`.
- If digest mismatch vs `pack.json` / `SHA256SUMS` → reject, keep previous pin / builtin.

### 3. Worker consistency without unsafe reload

| Event | Behavior |
|-------|----------|
| Pin unchanged | Cached renderer reused |
| Pin file mtime/content changes | Next request re-resolves pin; loads new version module if needed |
| Multi-worker | Each worker reads the same pin file; within one request generation they converge on the same version |

Optional ops hardening (preview/prod later): touch pin then `kill -HUP` / rolling restart workers so memory drops unused modules. **Not required for correctness** of pin selection.

### 4. Builtin fallback

`mode: "builtin"` uses the in-tree `CompositeService` true_color path (Stage C approved behavior).  
This is the **verified rollback target** when no prior pack artifact exists or pack fails verification.

Note: monolithic `true_color` 1.0.0 in the shell is **not** an independently deployable artifact; it is the compatibility fallback.

### 5. Promotion / rollback (dev)

- `scripts/tools/pack_promote_dev.py` — verify artifact, write pin.
- `scripts/tools/pack_rollback_dev.py` — pin previous version or builtin.
- Never called against production in E0/E1.
