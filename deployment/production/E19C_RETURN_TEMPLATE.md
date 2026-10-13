# E1.9C — Sanitized Results Return Template

Operator: paste this after scrubbing `$OUT` (see runbook §1 and §12).

```text
E1.9C inventory return
changes_made=none
hostname=
compose_project=
app_dir=/opt/earthvision
live_branch=
live_commit=
live_commit_short=
baseline_1e71b7a_ancestor=yes|no|object_missing
live_equals_approved_tip_e3012ce=no|yes
backend_image_id=
backend_repo_digest=
frontend_image_id=
frontend_repo_digest=
env_present=1|0
env_size=
env_sha256=
compose_sha256=
requirements_sha256=
named_volumes=          # comma-separated names only
bind_mount_destinations= # e.g. /data/imagery,/data/uploads,/data/cache,/data/logs
ev_pack_env_names_present=yes|no
tool_packs_volume_present=yes|no
local_health_http=
public_health_status=
tools_runtime_http=
composites_http=
runner_status=online|offline|unknown
runner_labels=
actions_runs_api=ok|fail|skipped
ci_gate_tip_e3012ce=ok|fail|unknown
preserve_dir_present=yes|no
STOP_triggered=no|yes (detail if yes)
secrets_in_bundle=no
```

Attach scrubbed files `01_identity.txt` … `15_manifest.txt` or `00_return_summary.txt` + redacted compose.
