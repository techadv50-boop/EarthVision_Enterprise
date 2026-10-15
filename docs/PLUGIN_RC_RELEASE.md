# SATEYE Independent Plugin System — Release Candidate

**Integration branch:** `cursor/sateye-plugin-rc-5d6d`  
**History preserved from:** P1 → P1.1 → P2A → P2A.1 (`f768092`) → P2B (`709b3a5`) → RC  
**Does not target / merge production branch.**

## Completed functionality

1. Plugin Manager (upload → validate → install → activate → disable → upgrade → rollback)  
2. Restricted worker (process isolation, signatures, active pin, Bearer + replay grants, optional mTLS)  
3. Sandboxed iframe FE loader for four slots + Host SDK 1.1.0 (meta, synthetic, resize, AOI, analysis results)  
4. demo_hello + demo_gis_analysis signed demo packs  
5. Admin health/compat/audit UI  
6. Preview compose overlay, seccomp allowlist, network internal + nftables helper  
7. Runbooks: admin, deploy, rollback, security verification, GO/NO-GO  

## Remaining blockers (precise)

See `docs/PLUGIN_RC_GO_NO_GO.md`.

## Production confirmation

**Production (`sateye.xdgen.com`) and production Dokploy services were not modified.**
