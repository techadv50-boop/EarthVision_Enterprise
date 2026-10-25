# Host library install (no image rebuild)

**Goal:** When a future plugin needs a Python package that is not already in the frozen `sateye-rs-2026.10` stack, install it like adding a package in Visual Studio / `pip` — **without rebuilding** frontend or backend images.

## Where in the UI

1. Sign in as **Admin**
2. Open **Admin** → **Plugins** tab  
   **or** Tools → **Installed plugins**
3. Section **“Host libraries (no rebuild)”**
4. **Upload .whl** (preferred)

**Upload Plugin** = tool pack zip only.  
**Host libraries** = Python prerequisites for the Host.

## How it works

| Item | Value |
|------|--------|
| Persistent dir | `/data/tool_packs/python_extras` (`EV_PYTHON_EXTRAS_DIR`) |
| Install method | `pip install --target` into that dir |
| Import path | `PYTHONPATH` + `sys.path` at backend startup |
| Survives | Container recreate (volume must be mounted) |
| Does **not** require | `docker compose build` |

If a long-lived worker already imported an old module, **restart** only:

```bash
sudo docker compose restart backend
# NOT: docker compose build
```

## Live compose requirement (one-time)

Ensure the backend service has the tool_packs volume and env (snippet: `deployment/compose.tool_packs.snippet.yml`):

```yaml
environment:
  EV_PYTHON_EXTRAS_DIR: /data/tool_packs/python_extras
  PYTHONPATH: /data/tool_packs/python_extras
volumes:
  - tool_packs_data:/data/tool_packs   # or your existing /data/tool_packs mount
```

## Optional PyPI allowlist

Default: wheel upload only.  
Set `EV_HOST_LIBS_ALLOW_PIP=1` to enable allowlisted `pip install` from the Admin UI.

## Security

- Admin role only  
- Prefer `.whl` upload (no arbitrary shell)  
- Max file size enforced  
- Audit via install manifest `EV_INSTALLED.json` in the extras dir  

## Relation to frozen profile

Base RS/GIS libs stay in `backend/requirements.txt` (`sateye-rs-2026.10`).  
**Extras** are additive for niche plugin prerequisites so the Host image stays stable.
