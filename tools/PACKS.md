# Tool Packs (E0 / E1)

## Status

- **E0:** Host SDK + runtime pins + pack loader + docs.
- **E1:** Only `true_color` has independently versioned artifacts.
- **Default pin:** `builtin` (in-tree `CompositeService` true_color — verified fallback, **not** an independent artifact).
- **Shell deploy:** unchanged (`Deploy SATEYE` full-app). Pack promote is **dev-only** via scripts.

## Artifacts

| Version | Digest |
|---------|--------|
| 1.0.0 | `sha256:e550e1a12cf72639e834dcdd77439ae5212b87d3ba7232151ad453fd3eb6536b` |
| 1.1.0 | `sha256:7e6ae07e6ec267d9f704d1384a93e8051d4791b5620ab2dd68dcc32643800f87` |

Paths: `tools/artifacts/true_color/<version>/`

## Dev commands

```bash
# Build (fails if version dir already exists — immutable)
python3 scripts/tools/build_true_color_pack.py --version 1.2.0

# Promote pin (verifies integrity first)
python3 scripts/tools/pack_promote_dev.py --version 1.0.0

# Rollback to prior pack or builtin
python3 scripts/tools/pack_rollback_dev.py --to 1.0.0
python3 scripts/tools/pack_rollback_dev.py --to builtin
```

## Docs

- `docs/TOOL_PACK_FRONTEND_LOADING.md`
- `docs/TOOL_PACK_BACKEND_ACTIVATION.md`
