# Plugin worker mTLS certificates (preview)

Generate locally (gitignored output under `tools/plugins/worker/certs/`):

```bash
python3 scripts/tools/generate_plugin_worker_mtls_certs.py
```

Never commit `*.key` or production CA material.
