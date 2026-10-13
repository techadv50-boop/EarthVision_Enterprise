# Stage E1.9C — Operator-Assisted Read-Only Production Inventory Runbook

**Status:** PREPARATION ONLY — execute on production by an authorized operator.  
**Date:** 2026-10-13  
**Approved deploy tip (unchanged):** `cursor/scene-download-eye-5d6d` @ `e3012ce0a26e049d0af981d5994d0d829c3b647e`  
**Scope:** Read-only inventory. **No** Deploy SATEYE, compose edits, restarts, Tool Pack install/activate, or Stage E2.

| Role | Action |
|------|--------|
| Cloud / development agent | Prepared this runbook; **must not** access production |
| Authorized operator | Runs this runbook on the production host; returns **sanitized** results |
| Owner | Reviews results; separately authorizes any future production change |

---

## 0. Expectations (STOP if mismatch)

| Attribute | Expected |
|-----------|----------|
| Hostname | `zhzh` |
| Application directory | `/opt/earthvision` |
| Dokploy / Compose project | `sateye-fz2ic4` |
| Public URL | `https://sateye.xdgen.com` |
| Deploy runner labels | `self-hosted`, `Linux`, `X64`, `sateye-live` |
| Imagery baseline (ancestor) | `1e71b7abaa0fa8d4b70225d949afc8ae79923bb6` (`sateye-baseline-20261012-1e71b7a`) |
| Approved Host Shell tip (not necessarily live) | `e3012ce0a26e049d0af981d5994d0d829c3b647e` |

**Global STOP:** If hostname ≠ `zhzh`, or app dir ≠ `/opt/earthvision`, or compose project ≠ `sateye-fz2ic4` (and no documented alias), **stop immediately**. Do not continue inventory on the wrong environment. Report the mismatch and await owner direction.

**Forbidden (entire runbook):**

- `docker compose up|down|pull|build|restart|stop|start|create|rm`
- `docker run`, `docker commit`, `docker tag` (except listing), `docker volume rm/create/prune`
- Mutating `docker compose exec` / `docker exec` (shell, SQL, file writes, package installs)
- `git checkout`, `git reset`, `git pull`, `git merge`, `git push`, `git clean`
- Editing compose, `.env`, credentials, permissions, networks, volumes, databases
- `workflow_dispatch` / Deploy SATEYE / any GitHub Actions run that deploys
- Printing secret **values** (passwords, tokens, private keys, DB URLs, `.env` contents)

**Allowed writes:** Create an output directory **outside** the app tree (recommended: `/tmp/e19c-inventory-<UTC>/`). Do not write under `/opt/earthvision`.

---

## 1. Redaction rules (mandatory)

Apply before sharing any file or paste:

| Class | Rule |
|-------|------|
| Environment variable **values** | Never paste; record **names only**, or `NAME=<redacted>` |
| `.env` | Record `present`, `size`, `sha256` only — never `cat` / never open in chat |
| Passwords / tokens / API keys | Redact entirely |
| Private keys / `.pem` / Ed25519 material | Do not open; record path existence only |
| Database / Redis URLs | Redact full string; may note scheme only (`postgresql`, `redis`) |
| `docker compose config` full dump | Run through redactor (script below) or omit values |
| Auth headers / cookies | Never include |
| User imagery / uploads / DB rows | Do not read |

**Safe to return:** hostnames, paths, service names, volume **names**, mount **destinations**, image IDs/digests, git SHAs/branches, file checksums, HTTP status codes, boolean presence flags, redacted env **names**.

---

## 2. Setup (operator workstation / production host)

```bash
# Safety explanation: creates ONLY a temp output dir; does not touch the app.
set -euo pipefail
OUT="/tmp/e19c-inventory-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT"
echo "OUT=$OUT" | tee "$OUT/00_out_path.txt"
# Optional: copy tip scripts to a side directory (NOT into /opt/earthvision).
# Prefer running the embedded commands in this runbook, or:
#   SCRIPTS=/tmp/e19c-scripts  # populate from tip e3012ce checkout elsewhere
```

Optional all-in-one helper (from tip tree, run from a side checkout — never copy into live app):

```bash
# Safety: script writes only under OUT; refuses APP_DIR writes; redacts secrets.
# APP_DIR=/opt/earthvision OUT_DIR="$OUT" bash scripts/e19c_operator_inventory.sh
```

If the helper is unavailable, execute sections 3–10 manually.

---

## 3. Identity — host, app dir, compose project, services

```bash
# Safety: read-only identity probes. STOP on mismatch.
{
  echo "captured_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "hostname=$(hostname)"
  echo "whoami=$(whoami)"
  echo "pwd=$(pwd)"
  echo "app_dir_exists=$([[ -d /opt/earthvision ]] && echo 1 || echo 0)"
} | tee "$OUT/01_identity.txt"

HOST_OK=0
[[ "$(hostname)" == "zhzh" ]] && HOST_OK=1
APP_OK=0
[[ -d /opt/earthvision ]] && APP_OK=1
echo "host_ok=$HOST_OK app_ok=$APP_OK" | tee -a "$OUT/01_identity.txt"
if [[ "$HOST_OK" != "1" || "$APP_OK" != "1" ]]; then
  echo "STOP: hostname or /opt/earthvision mismatch — do not continue" | tee "$OUT/STOP.txt"
  exit 2
fi

cd /opt/earthvision

# Compose project name from running containers (read-only)
{
  echo "=== docker compose ls ==="
  docker compose ls 2>/dev/null || true
  echo "=== container project labels ==="
  docker ps --format '{{.Names}}\t{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.service"}}\t{{.Status}}\t{{.Image}}' 2>/dev/null || true
} | tee "$OUT/02_compose_project.txt"

PROJECT="$(docker ps --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null | grep -v '^$' | sort -u | head -5 || true)"
echo "detected_projects<<EOF" >> "$OUT/02_compose_project.txt"
echo "$PROJECT" >> "$OUT/02_compose_project.txt"
echo "EOF" >> "$OUT/02_compose_project.txt"

# STOP if project clearly wrong (allow only sateye-fz2ic4; note others)
if echo "$PROJECT" | grep -q . && ! echo "$PROJECT" | grep -qx 'sateye-fz2ic4'; then
  if ! echo "$PROJECT" | grep -q 'sateye-fz2ic4'; then
    echo "STOP: compose project(s) [$PROJECT] do not include expected sateye-fz2ic4" | tee "$OUT/STOP.txt"
    exit 3
  fi
fi

# Active services (status only)
{
  echo "=== docker compose ps ==="
  docker compose ps 2>/dev/null || true
  echo "=== service names ==="
  docker compose config --services 2>/dev/null || true
} | tee "$OUT/03_services.txt"
```

**Expected output fields:** `hostname`, `app_dir_exists`, `detected_projects`, service names, container status strings, image name tags (not digests yet).

---

## 4. Live Git SHA, branch, baseline ancestry

```bash
# Safety: git read-only queries only — no fetch/pull/checkout/reset.
cd /opt/earthvision
{
  echo "branch=$(git branch --show-current 2>/dev/null || true)"
  echo "commit=$(git rev-parse HEAD 2>/dev/null || true)"
  echo "commit_short=$(git rev-parse --short HEAD 2>/dev/null || true)"
  echo "dirty=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  # Do NOT paste git status porcelain paths if they might include secret filenames; summary only:
  echo "status_summary_lines=$(git status -sb 2>/dev/null | head -1)"
  BASELINE=1e71b7abaa0fa8d4b70225d949afc8ae79923bb6
  TIP=e3012ce0a26e049d0af981d5994d0d829c3b647e
  if git cat-file -e "${BASELINE}^{commit}" 2>/dev/null; then
    if git merge-base --is-ancestor "$BASELINE" HEAD 2>/dev/null; then
      echo "baseline_1e71b7a_ancestor=yes"
    else
      echo "baseline_1e71b7a_ancestor=no"
    fi
  else
    echo "baseline_1e71b7a_object=missing_locally"
  fi
  if [[ "$(git rev-parse HEAD 2>/dev/null || echo none)" == "$TIP" ]]; then
    echo "live_equals_approved_tip_e3012ce=yes"
  else
    echo "live_equals_approved_tip_e3012ce=no"
  fi
  # Tag presence (name only)
  echo "baseline_tag=$(git tag -l 'sateye-baseline-20261012-1e71b7a' 2>/dev/null || true)"
} | tee "$OUT/04_git.txt"

# Fingerprints only (no file contents)
{
  [[ -f .env ]] && echo "env_present=1 env_size=$(wc -c < .env | tr -d ' ') env_sha256=$(sha256sum .env | awk '{print $1}')" || echo "env_present=0"
  [[ -f docker-compose.yml ]] && echo "compose_sha256=$(sha256sum docker-compose.yml | awk '{print $1}')" || echo "compose=MISSING"
  [[ -f backend/requirements.txt ]] && echo "requirements_sha256=$(sha256sum backend/requirements.txt | awk '{print $1}')" || true
} | tee "$OUT/05_fingerprints.txt"
```

**Expected output fields:** `branch`, `commit`, `commit_short`, `baseline_1e71b7a_ancestor`, `live_equals_approved_tip_e3012ce`, `env_sha256`, `compose_sha256`.

**Interpretation:** `baseline_1e71b7a_ancestor=yes` means imagery-fix baseline is in history of the live checkout. `live_equals_approved_tip_e3012ce=no` is **expected** until Host Shell deploy is separately authorized.

---

## 5. Image IDs, digests, rollback availability

```bash
# Safety: inspect/list only — no pull/build/rmi/tag.
cd /opt/earthvision
{
  echo "=== compose images ==="
  docker compose images 2>/dev/null || true
  echo "=== backend/frontend Id + RepoDigests + Created ==="
  for svc in backend frontend; do
    id="$(docker compose images -q "$svc" 2>/dev/null | head -1 || true)"
    if [[ -n "${id:-}" ]]; then
      docker image inspect "$id" --format "$svc Id={{.Id}} RepoDigests={{json .RepoDigests}} RepoTags={{json .RepoTags}} Created={{.Created}} Size={{.Size}}" 2>/dev/null || true
    else
      echo "$svc Id=MISSING"
    fi
  done
  echo "=== local image inventory (Id/Repository/Tag/Digest) — no history wipe ==="
  docker images --digests --format '{{.ID}}\t{{.Repository}}\t{{.Tag}}\t{{.Digest}}\t{{.CreatedSince}}' 2>/dev/null | head -80 || true
} | tee "$OUT/06_images.txt"

# Rollback readiness: prior image still present?
{
  echo "=== preserve dir listing (names/mtime only) ==="
  PRESERVE="${PRESERVE_DIR:-/home/zh/earthvision-deploy-preserve}"
  echo "preserve_dir=$PRESERVE"
  if [[ -d "$PRESERVE" ]]; then
    ls -la "$PRESERVE" 2>/dev/null | head -50 || true
  else
    echo "preserve_dir_missing=1"
  fi
  echo "=== note ==="
  echo "Record CURRENT backend/frontend Id+RepoDigests above as PRIOR_* for any future cutover."
  echo "Rollback images are 'available' if those Ids still appear in docker images --digests."
} | tee "$OUT/07_rollback.txt"
```

**Expected output fields:** per-service `Id`, `RepoDigests`, `RepoTags`, `Created`; preserve-dir presence; whether current IDs remain in local image store (they are the live ones — also list any older `sateye`/`earthvision` tags still present).

---

## 6. Effective Compose (redacted)

Prefer the helper redactor. Manual fallback:

```bash
# Safety: dumps structure; VALUES must be redacted before leaving the host.
cd /opt/earthvision

# Service list + volume names + networks (compose config can embed secrets — redact!)
docker compose config --services 2>/dev/null | tee "$OUT/08_compose_services.txt"

# Redacted config via Python (stdlib only)
python3 - <<'PY' | tee "$OUT/09_compose_redacted.yml"
import re, subprocess, sys
from pathlib import Path

SENSITIVE = re.compile(
    r"(PASSWORD|SECRET|TOKEN|PRIVATE|API[_-]?KEY|AUTH|CREDENTIAL|DATABASE_URL|"
    r"POSTGRES|REDIS_URL|CONNECTION|ADMIN_PASS|JWT|SESSION|SMTP|AWS_|GCP_|GOOGLE_|"
    r"PRIVATE_KEY|PUBLISHER.*KEY)",
    re.I,
)
CONN = re.compile(r"(?i)\b(postgres|postgresql|redis|mysql|mongodb)://\S+")

def redact_line(line: str) -> str:
    # KEY: value or KEY=value
    m = re.match(r"^(\s*)([A-Za-z0-9_]+)(\s*[=:]\s*)(.*)$", line)
    if m:
        indent, key, sep, val = m.groups()
        if SENSITIVE.search(key) or CONN.search(val) or re.search(r"(?i)(password|secret|token)", val):
            return f"{indent}{key}{sep}<redacted>\n"
        # Long opaque strings that look like secrets
        if len(val.strip()) > 40 and re.fullmatch(r"[A-Za-z0-9+/=_\-]{40,}", val.strip().strip('\"\'')):
            return f"{indent}{key}{sep}<redacted>\n"
    return CONN.sub(r"\1://<redacted>", line)

try:
    raw = subprocess.check_output(
        ["docker", "compose", "config"],
        stderr=subprocess.STDOUT,
        text=True,
    )
except Exception as e:
    print(f"# compose_config_error: {e}", file=sys.stderr)
    sys.exit(0)

for line in raw.splitlines(True):
    sys.stdout.write(redact_line(line))
PY

# Mount destinations only (no file contents)
{
  echo "=== volume names ==="
  docker volume ls --format '{{.Name}}\t{{.Driver}}' 2>/dev/null | egrep -i 'sateye|earthvision|pgdata|postgres|tool_pack|fz2ic4' || docker volume ls
  echo "=== container mounts (Source may be host path; do not ls data dirs recursively) ==="
  for cid in $(docker compose ps -q 2>/dev/null); do
    docker inspect "$cid" --format '{{.Name}} {{range .Mounts}}{{.Type}}:{{.Name}}{{.Source}}->{{.Destination}} {{end}}' 2>/dev/null || true
  done
} | tee "$OUT/10_volumes_mounts.txt"
```

**Expected output fields:** service list; named volume names; bind-mount host path → container destination; env **names** (values `<redacted>`); networks.

**Confirm storage pattern (names/paths only):**

| Expectation | Look for |
|-------------|----------|
| PostgreSQL | named volume containing `pgdata` / `postgres` |
| imagery / uploads / cache / logs | bind mounts to `/data/imagery`, `/data/uploads`, `/data/cache`, `/data/logs` (or host `./imagery` etc.) |
| tool_packs | likely **absent** until Host Shell overlay |

---

## 7. Service health (no data reads)

```bash
# Safety: HTTP/process health only — no SQL, no file reads inside volumes.
{
  echo "=== compose ps ==="
  docker compose ps 2>/dev/null || true
  echo "=== local health URLs ==="
  for url in \
      http://127.0.0.1:8080/health \
      http://127.0.0.1:8000/health \
      http://127.0.0.1:8100/health \
      http://127.0.0.1:8101/health
  do
    code=$(curl -sS -m 5 -o /tmp/e19c_hbody.txt -w '%{http_code}' "$url" 2>/dev/null || echo ERR)
    # Record status + non-secret JSON keys only
    echo -n "$url -> $code "
    if [[ -f /tmp/e19c_hbody.txt ]]; then
      python3 - <<'PY'
import json,sys
p="/tmp/e19c_hbody.txt"
try:
    d=json.load(open(p))
    keep={k:d.get(k) for k in ("status","version","environment","database") if k in d}
    print(keep)
except Exception:
    print("(non-json-or-empty)")
PY
    fi
  done
  echo "=== public health (optional from host) ==="
  curl -sS -m 8 -w '\nhttp=%{http_code}\n' https://sateye.xdgen.com/health 2>/dev/null | python3 -c 'import sys,json,re
t=sys.stdin.read().strip().splitlines()
body="\n".join(t[:-1]) if t else ""
print(t[-1] if t else "")
try:
 d=json.loads(body); print({k:d.get(k) for k in ("status","version","environment","database")})
except Exception: print("body_redacted_or_non_json")'
} | tee "$OUT/11_health.txt"

# Env NAMES inside running backend (values redacted) — inspect only, no exec shell
{
  echo "=== backend container env NAMES (values redacted) ==="
  cid=$(docker compose ps -q backend 2>/dev/null | head -1 || true)
  if [[ -n "${cid:-}" ]]; then
    docker inspect "$cid" --format '{{range .Config.Env}}{{println .}}{{end}}' \
      | sed -E 's/^([^=]+)=.*/\1=<redacted>/' \
      | sort
  else
    echo "backend_container=MISSING"
  fi
  echo "=== trust-related names present? ==="
  docker inspect "$cid" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
    | sed -E 's/=.*//' \
    | egrep '^(EV_PACK_|EV_TOOL_|EV_RUNTIME_|EV_ARTIFACTS_)' || echo "no_EV_PACK_env_names"
} | tee "$OUT/12_env_names.txt"
```

**Expected output fields:** container health state; HTTP codes; `status`/`database` from health JSON; list of env names; whether any `EV_PACK_*` names exist (likely none pre-Host-Shell).

---

## 8. Deployment runner availability & GitHub permissions (no workflow trigger)

Run on the **Actions runner host** if different from the app host; if colocated on `zhzh`, run here.

```bash
# Safety: process/API read-only. Do NOT gh workflow run / workflow_dispatch.
{
  echo "hostname=$(hostname)"
  echo "=== runner processes (names only) ==="
  ps aux 2>/dev/null | egrep -i 'actions\.runner|Runner\.Listener|sateye-live' | grep -v egrep | awk '{print $1,$2,$11,$12,$13,$14,$15}' | head -20 || true
  echo "=== systemd units (if any) ==="
  systemctl list-units --type=service --all 2>/dev/null | egrep -i 'actions.runner|github' | head -20 || true
  echo "=== gh auth status (no tokens printed) ==="
  if command -v gh >/dev/null; then
    gh auth status 2>&1 | sed -E 's/[A-Za-z0-9_]{20,}/<redacted>/g' || true
    echo "=== API: list runners (needs admin: read) ==="
    gh api repos/techadv50-boop/EarthVision_Enterprise/actions/runners \
      --jq '.runners[]? | {name,id,status,busy,labels:[.labels[].name]}' 2>&1 \
      | sed -E 's/(token|secret)[^"]*/\1<redacted>/gi' || echo "runners_api_failed"
    echo "=== API: exact-SHA gate dry-run (read actions runs only) ==="
    DEPLOY_CI_GATE_SHA=e3012ce0a26e049d0af981d5994d0d829c3b647e \
    DEPLOY_CI_GATE_REPO=techadv50-boop/EarthVision_Enterprise \
    bash -c 'command -v gh >/dev/null && gh api "repos/$DEPLOY_CI_GATE_REPO/actions/runs?head_sha=$DEPLOY_CI_GATE_SHA&per_page=20" --jq "{count:(.workflow_runs|length), runs:[.workflow_runs[]|{name,path,head_sha,status,conclusion,event}]}"' \
      2>&1 || echo "actions_runs_api_failed"
  else
    echo "gh_missing=1"
  fi
  echo "=== DO NOT RUN ==="
  echo "forbidden: gh workflow run deploy-sateye.yml"
  echo "forbidden: any confirm=deploy dispatch"
} | tee "$OUT/13_runner.txt"
```

**Expected output fields:** runner process present/absent; runner `status` (`online`/`offline`); labels including `sateye-live`; whether Actions runs API returns CI/Tool Protection success for `e3012ce`; auth failure codes if permissions insufficient.

**Manual UI fallback (no API):** GitHub → repo → Settings → Actions → Runners → confirm a runner with label `sateye-live` is **Idle/Online**. Screenshot or note name+status only.

---

## 9. Production deployment configuration vs baseline imagery fixes

```bash
# Safety: read-only git + path existence. No data directory recursion into imagery blobs.
cd /opt/earthvision
{
  echo "commit=$(git rev-parse HEAD)"
  echo "baseline_check_ref=1e71b7abaa0fa8d4b70225d949afc8ae79923bb6"
  git merge-base --is-ancestor 1e71b7abaa0fa8d4b70225d949afc8ae79923bb6 HEAD \
    && echo baseline_ancestor=yes || echo baseline_ancestor=no
  # Presence of known imagery-related paths in the TREE (not user data files)
  for p in \
      backend/app/services \
      frontend/src \
      docker-compose.yml
  do
    [[ -e "$p" ]] && echo "path_present=$p" || echo "path_missing=$p"
  done
  # Host Shell endpoint expectation on LIVE (public or local): tools/runtime often 404 until tip deploy
  code=$(curl -sS -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/v1/tools/runtime 2>/dev/null || echo ERR)
  echo "local_tools_runtime_http=$code"
  code2=$(curl -sS -m 8 -o /dev/null -w '%{http_code}' https://sateye.xdgen.com/api/v1/tools/runtime 2>/dev/null || echo ERR)
  echo "public_tools_runtime_http=$code2"
  code3=$(curl -sS -m 8 -o /dev/null -w '%{http_code}' https://sateye.xdgen.com/api/v1/analytics/composites 2>/dev/null || echo ERR)
  echo "public_composites_http=$code3  # expect 401 if route exists without auth"
} | tee "$OUT/14_baseline_and_config.txt"
```

**Expected output fields:** `baseline_ancestor`, path presence flags, HTTP codes for tools/runtime and composites.

---

## 10. Package results (sanitized)

```bash
# Safety: archive only the OUT dir; scrub any accidental secrets.
cd "$OUT"
# Fail closed if someone accidentally dumped .env
if grep -R -l -E '(?i)(BEGIN (RSA |OPENSSH )?PRIVATE KEY|postgres(ql)?://[^<]|password\s*[:=]\s*[^<])' . 2>/dev/null; then
  echo "STOP: possible secret material in OUT — scrub before sharing" | tee STOP_SECRETS.txt
fi

{
  echo "e19c_inventory_complete=1"
  echo "out=$OUT"
  echo "file_count=$(find . -type f | wc -l)"
  find . -type f | sort
} | tee "$OUT/15_manifest.txt"

# Create a tarball the operator can copy off-box
tar -C /tmp -czf "/tmp/$(basename "$OUT").tar.gz" "$(basename "$OUT")"
echo "tarball=/tmp/$(basename "$OUT").tar.gz"
sha256sum "/tmp/$(basename "$OUT").tar.gz"
```

---

## 11. Verification checklist (operator)

Mark each PASS/FAIL/STOP:

| # | Check | Result |
|---|-------|--------|
| V1 | Hostname is `zhzh` | |
| V2 | `/opt/earthvision` exists | |
| V3 | Compose project includes `sateye-fz2ic4` | |
| V4 | Live `git rev-parse HEAD` recorded | |
| V5 | Live branch recorded | |
| V6 | Backend + frontend image Id + RepoDigests recorded | |
| V7 | Compose services + redacted config captured | |
| V8 | Volume names + mount destinations recorded (no data reads) | |
| V9 | `.env` present + size + sha256 only | |
| V10 | `baseline_1e71b7a_ancestor` determined | |
| V11 | Health endpoints checked (local and/or public) | |
| V12 | Runner online / `sateye-live` label verified **without** workflow_dispatch | |
| V13 | Actions runs API (or UI) can see CI status for `e3012ce` | |
| V14 | Rollback: current digests + any older local images / preserve dir noted | |
| V15 | No secrets in shared bundle (redaction review) | |
| V16 | No production changes made | |

Any **STOP** or unexpected project/host → do not proceed to deployment discussions until owner clears identity.

---

## 12. How to return sanitized results

1. Review every file under `$OUT` for leaked secrets (section 1 rules).
2. Prefer sending:
   - `01_identity.txt` … `15_manifest.txt` (all of them), **or**
   - the `.tar.gz` after local scrub
3. Return via the owner’s approved channel (PR comment paste of **non-secret** summaries, secure ops channel, or attached scrubbed archive).
4. Explicitly include these summary lines in the message body:

```text
hostname=
compose_project=
app_dir=/opt/earthvision
live_branch=
live_commit=
baseline_1e71b7a_ancestor=
backend_image_id=
backend_repo_digest=
frontend_image_id=
frontend_repo_digest=
env_sha256=
compose_sha256=
runner_status=
actions_runs_api=ok|fail
tools_runtime_http=
composites_http=
ev_pack_env_names_present=yes|no
changes_made=none
```

5. Do **not** begin Stage E2 or request Deploy SATEYE in the same message unless the owner already authorized it separately.

---

## 13. Blockers this inventory can resolve

| Blocker ID | Resolvable by E1.9C inventory? | How |
|------------|--------------------------------|-----|
| **B-HOST** | **Yes** | Confirm `zhzh` + `/opt/earthvision` + `sateye-fz2ic4` on-box |
| **B-DIGESTS** | **Yes** | Capture live git SHA + backend/frontend Ids/RepoDigests |
| **B-OVERLAY** (inspect) | **Partial** | Redacted compose shows whether Tool Pack keys/volume absent/present; does **not** apply merge |
| **B-RUNNER** | **Yes / Partial** | Process/API/UI proves `sateye-live` online + Actions runs readability |
| **B-CI (live token)** | **Partial** | Gate dry-run / `actions/runs?head_sha=` from runner host |
| **B-TRUST (live)** | **Partial** | Env name presence / publishers path existence; no key install |
| **B-KEYS** | **No** | Still requires offline key provisioning (separate authorization) |
| **B-ADMIN** | **No** (already code-fixed on tip) | Tip protection; not applied until authorized Deploy |
| Cutover / Deploy | **No** | Requires explicit later approval |
| Stage E2 | **No** | Out of scope |

---

## 14. Updated GO / NO-GO (after inventory returns)

- **Until sanitized results are reviewed by the owner:** remains **NO-GO** for production modification / Host Shell Deploy SATEYE.
- Inventory success clears host/digest/runner unknowns; it does **not** by itself authorize deployment.

---

**END OF E1.9C RUNBOOK — STOP after operator execution and owner review.**
