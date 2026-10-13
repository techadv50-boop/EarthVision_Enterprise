# E1.9C-R1 — Sanitized Results Return Template

Operator: complete only after reviewing `15_manifest.txt`.

**Do not return a bundle when `share_safe=no` or `STOP_SECRETS.txt` is present.**

```text
E1.9C-R1 inventory return
changes_made=none
share_safe=yes|no
secret_scanner=OK|FAIL
archive_allowed=yes|no
identity_result=PASS|STOP
hostname=
compose_project=sateye-fz2ic4|UNKNOWN
app_dir=/opt/earthvision
backend_container=
frontend_container=
proxy_container=
proxy_service_label=nginx|caddy|traefik|proxy|edge|UNKNOWN
live_branch=
live_commit=
live_commit_short=
baseline_1e71b7a_ancestor=yes|no|object_missing|UNKNOWN
live_equals_approved_tip_e3012ce=no|yes|UNKNOWN
backend_image_id=
backend_repo_digest=
frontend_image_id=
frontend_repo_digest=
proxy_image_id=
env_present=1|0
env_size=
env_sha256=
compose_sha256=
requirements_sha256=
named_volumes=
bind_mount_destinations=
ev_pack_env_names_present=yes|no|UNKNOWN
tool_packs_volume_present=yes|no|UNKNOWN
local_health_http=
public_health_status=
tools_runtime_http=
composites_http=
runner_status=online|offline|UNKNOWN|skipped
runner_labels=
actions_runs_api=ok|denied|unauthorized|not_found|error|skipped|UNKNOWN
ci_gate_tip_e3012ce=ok|fail|UNKNOWN
preserve_dir_present=yes|no|UNKNOWN
STOP_triggered=no|yes
STOP_detail=
secrets_in_bundle=no
```

Attach when share-safe: `00_return_summary.txt`, `01_identity.txt`, `02_project_services.json`, `04_git.txt`–`15_manifest.txt` (scrubbed). Omit `STOP_SECRETS.txt` bundles.
