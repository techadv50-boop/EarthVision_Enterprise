#!/usr/bin/env python3
"""Adversarial safety tests for E1.9C-R1 inventory helper (no production access)."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from e19c_inventory_lib import (  # noqa: E402
    allowlisted_health_fields,
    parse_compose_structure,
    run_inventory,
    scan_for_secrets,
    scrub_gh_error,
    verify_project_services,
)

PASS = 0
FAIL = 0


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        print(f"PASS: {name}")
        PASS += 1
    else:
        print(f"FAIL: {name} {detail}", file=sys.stderr)
        FAIL += 1


SECRET_COMPOSE = """
services:
  backend:
    image: ev-backend:live
    environment:
      DATABASE_URL: postgresql://user:SuperSecretPass@db:5432/earthvision
      POSTGRES_PASSWORD: hunter2
      JWT_SECRET: aabbccddeeff00112233445566778899
      EV_PACK_PUBLISHERS: /data/tool_packs/publishers/approved_publishers.json
      NORMAL_FLAG: "1"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./imagery:/data/imagery
      - ./uploads:/data/uploads
  frontend:
    image: ev-frontend:live
    environment:
      API_TOKEN: tok_live_SHOULD_NOT_LEAK
  nginx:
    image: ev-nginx:live
    ports:
      - "8080:80"
  unrelated:
    image: other:1
volumes:
  pgdata:
networks:
  default:
"""

MULTI_PROJECT_PS = "\n".join(
    [
        # Wrong project also has backend/frontend/nginx — must NOT satisfy identity alone
        "preview-backend\tsateye-preview\tbackend\tUp\tpreview-backend:1",
        "preview-frontend\tsateye-preview\tfrontend\tUp\tpreview-frontend:1",
        "preview-nginx\tsateye-preview\tnginx\tUp\tpreview-nginx:1",
        # Expected project — incomplete (missing proxy) for one test; complete for another
    ]
)

COMPLETE_PS = "\n".join(
    [
        "preview-backend\tsateye-preview\tbackend\tUp\tpreview-backend:1",
        "sateye-fz2ic4-backend-1\tsateye-fz2ic4\tbackend\tUp\tev-backend:live",
        "sateye-fz2ic4-frontend-1\tsateye-fz2ic4\tfrontend\tUp\tev-frontend:live",
        "sateye-fz2ic4-nginx-1\tsateye-fz2ic4\tnginx\tUp\tev-nginx:live",
    ]
)

INCOMPLETE_PS = "\n".join(
    [
        "sateye-fz2ic4-backend-1\tsateye-fz2ic4\tbackend\tUp\tev-backend:live",
        "sateye-fz2ic4-frontend-1\tsateye-fz2ic4\tfrontend\tUp\tev-frontend:live",
        # proxy missing
        "other-nginx\tsateye-preview\tnginx\tUp\tpreview-nginx:1",
    ]
)


class MockCmd:
    def __init__(self, scenario: str, app_dir: Path) -> None:
        self.scenario = scenario
        self.app_dir = app_dir
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> tuple[int, str, str]:
        self.calls.append(list(argv))
        op = argv[0]
        if op == "hostname":
            if self.scenario == "wrong_host":
                return 0, "cursor\n", ""
            return 0, "zhzh\n", ""
        if op == "docker" and argv[1] == "ps":
            if self.scenario == "docker_ps_fail":
                return 1, "", "permission denied"
            if self.scenario == "incomplete_services":
                return 0, INCOMPLETE_PS + "\n", ""
            if self.scenario == "multi_project_only_preview":
                return 0, MULTI_PROJECT_PS + "\n", ""
            return 0, COMPLETE_PS + "\n", ""
        if op == "docker" and argv[1] == "inspect":
            # Always include a secret in raw inspect to ensure we don't write it
            name = argv[2]
            if "--format" in argv and "Config.Env" in " ".join(argv):
                return (
                    0,
                    "DATABASE_URL=postgresql://user:SuperSecretPass@db:5432/ev\n"
                    "POSTGRES_PASSWORD=hunter2\n"
                    "EV_PACK_TRUST_PROFILE=production\n"
                    "NORMAL_FLAG=1\n",
                    "",
                )
            if "--format" in argv and "Mounts" in " ".join(argv):
                return 0, "volume pgdata /var/lib/docker/volumes/pgdata/_data /var/lib/postgresql/data\nbind  /opt/earthvision/imagery /data/imagery\n", ""
            if "--format" in argv and ".Image" in " ".join(argv):
                return 0, "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa ev-backend:live\n", ""
            return 0, "", ""
        if op == "docker" and argv[1] == "image":
            return (
                0,
                '["ev-backend@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]|||["ev-backend:live"]\n',
                "",
            )
        if op == "tar":
            # Archive is built in-process via tarfile; shell tar should not be required.
            return 0, "", ""
        if op == "docker" and argv[1] == "volume":
            return 0, "sateye-fz2ic4_pgdata\tlocal\nother_project_vol\tlocal\n", ""
        if op == "git":
            # git -C app_dir ...
            if "rev-parse" in argv and "HEAD" in argv and "--short" not in argv:
                return 0, "1e71b7abaa0fa8d4b70225d949afc8ae79923bb6\n", ""
            if "rev-parse" in argv and "--short" in argv:
                return 0, "1e71b7a\n", ""
            if "branch" in argv:
                return 0, "cursor/scene-download-eye-5d6d\n", ""
            if "status" in argv:
                return 0, "## cursor/scene-download-eye-5d6d\n", ""
            if "cat-file" in argv:
                return 0, "", ""
            if "merge-base" in argv:
                return 0, "", ""
            return 0, "", ""
        if op == "sha256sum":
            return 0, "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef  file\n", ""
        if op == "curl":
            if "/tools/runtime" in " ".join(argv):
                if "-o" in argv and "/dev/null" in argv:
                    return 0, "404", ""
                return 0, '{"detail":"Not Found"}\n__HTTP__404', ""
            if "composites" in " ".join(argv):
                if "-o" in argv:
                    return 0, "401", ""
                return 0, '{"detail":"Missing authentication credentials"}\n__HTTP__401', ""
            # health with secret that must not be retained
            return (
                0,
                '{"status":"healthy","database":"postgresql","password":"SHOULD_NOT_APPEAR","version":"1.0.0","environment":"development"}\n__HTTP__200',
                "",
            )
        if op == "gh":
            if self.scenario == "gh_forbidden":
                return 1, "", "gh: Resource not accessible by integration (HTTP 403)"
            if "actions/runners" in " ".join(argv):
                payload = {
                    "runners": [
                        {
                            "id": 1,
                            "name": "sateye-live-1",
                            "status": "online",
                            "busy": False,
                            "labels": [{"name": "sateye-live"}, {"name": "Linux"}],
                            "secret_token": "LEAKME",
                        }
                    ]
                }
                return 0, json.dumps(payload), ""
            if "actions/runs" in " ".join(argv):
                payload = {
                    "workflow_runs": [
                        {
                            "name": "CI",
                            "path": ".github/workflows/ci.yml",
                            "head_sha": "e3012ce0a26e049d0af981d5994d0d829c3b647e",
                            "status": "completed",
                            "conclusion": "success",
                            "event": "push",
                            "logs_url": "https://example.invalid/secret",
                        }
                    ]
                }
                return 0, json.dumps(payload), ""
            return 1, "", "unexpected"
        return 127, "", "command_not_found"


def _prep_app(tmpdir: Path) -> Path:
    app = tmpdir / "opt" / "earthvision"
    app.mkdir(parents=True)
    (app / ".git").mkdir()
    (app / "backend").mkdir()
    (app / "backend" / "requirements.txt").write_text("fastapi==0.0\n", encoding="utf-8")
    (app / ".env").write_text("POSTGRES_PASSWORD=hunter2\nDATABASE_URL=postgresql://x:y@z/db\n", encoding="utf-8")
    (app / "docker-compose.yml").write_text(SECRET_COMPOSE, encoding="utf-8")
    return app


def test_wrong_host_stops_without_inventory() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        app = _prep_app(td_path)
        out = td_path / "out-wrong-host"
        mock = MockCmd("wrong_host", app)
        result = run_inventory(
            app_dir=str(app),
            out_dir=str(out),
            expected_host="zhzh",
            expected_project="sateye-fz2ic4",
            cmd=mock,
            include_runner_checks=False,
            hostname_value="cursor",
        )
        ok("wrong host => STOP", result.status == "STOP")
        ok("wrong host share_safe=false", result.share_safe is False)
        names = set(result.files)
        ok(
            "wrong host does not invent images inventory",
            "06_images.txt" not in names and "09_compose_structure.json" not in names,
            detail=str(names),
        )
        ok("wrong host writes STOP.txt", "STOP.txt" in names)
        # Ensure docker inspect never called after identity failure
        inspect_calls = [c for c in mock.calls if c[:2] == ["docker", "inspect"]]
        ok("wrong host: no docker inspect", inspect_calls == [], detail=str(inspect_calls))


def test_project_exists_but_required_services_on_other_project_stops() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        app = _prep_app(td_path)
        out = td_path / "out-preview-only"
        mock = MockCmd("multi_project_only_preview", app)
        result = run_inventory(
            app_dir=str(app),
            out_dir=str(out),
            cmd=mock,
            include_runner_checks=False,
            hostname_value="zhzh",
        )
        ok("preview-only services => STOP", result.status == "STOP")
        ok(
            "no image inventory after service identity fail",
            "06_images.txt" not in result.files,
        )
        inspect_calls = [c for c in mock.calls if c[:2] == ["docker", "inspect"]]
        ok("no docker inspect when services missing", inspect_calls == [])


def test_incomplete_required_services_stops() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        app = _prep_app(td_path)
        out = td_path / "out-incomplete"
        mock = MockCmd("incomplete_services", app)
        result = run_inventory(
            app_dir=str(app),
            out_dir=str(out),
            cmd=mock,
            include_runner_checks=False,
            hostname_value="zhzh",
        )
        ok("missing proxy => STOP", result.status == "STOP")
        stop = result.files.get("STOP.txt", "")
        ok("STOP mentions proxy", "proxy" in stop)


def test_secrets_never_appear_in_shared_outputs() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        app = _prep_app(td_path)
        out = td_path / "out-ok"
        mock = MockCmd("happy", app)
        result = run_inventory(
            app_dir=str(app),
            out_dir=str(out),
            cmd=mock,
            include_runner_checks=True,
            hostname_value="zhzh",
            approved_tip="e3012ce0a26e049d0af981d5994d0d829c3b647e",
        )
        ok("happy path status OK", result.status == "OK", detail=str(result.stop_reason))
        blob = "\n".join(result.files.values())
        for banned in (
            "SuperSecretPass",
            "hunter2",
            "tok_live_SHOULD_NOT_LEAK",
            "aabbccddeeff00112233445566778899",
            "SHOULD_NOT_APPEAR",
            "LEAKME",
            "postgresql://user:",
        ):
            ok(f"secret absent: {banned}", banned not in blob)
        # Structure has env NAMES only
        structure = json.loads(result.files["09_compose_structure.json"])
        env_names = structure["services"]["backend"]["env_names"]
        ok("compose structure keeps DATABASE_URL name", "DATABASE_URL" in env_names)
        ok(
            "compose structure has no env values",
            "hunter2" not in json.dumps(structure) and "postgresql://" not in json.dumps(structure),
        )
        # Health password field scrubbed/not present as secret
        ok("health body password not present", "SHOULD_NOT_APPEAR" not in result.files["11_health.txt"])
        # Runner token stripped
        ok("runner secret_token absent", "LEAKME" not in result.files["13_runner.txt"])
        ok("share_safe true when clean", result.share_safe is True)
        ok("archive allowed when clean", "archive_allowed=yes" in result.files["15_manifest.txt"])


def test_compose_structure_allowlist() -> None:
    structure = parse_compose_structure(SECRET_COMPOSE)
    dumped = json.dumps(structure)
    ok("no password values in structure", "hunter2" not in dumped and "SuperSecretPass" not in dumped)
    ok("env names present", "POSTGRES_PASSWORD" in structure["services"]["backend"]["env_names"])
    ok("named volume listed", "pgdata" in structure["named_volumes"])


def test_health_allowlist() -> None:
    fields = allowlisted_health_fields(
        '{"status":"healthy","database":"postgresql","password":"x","token":"y","version":"1"}'
    )
    ok("health keeps status", fields.get("status") == "healthy")
    ok("health drops password key", "password" not in fields)
    ok("health drops token key", "token" not in fields)


def test_gh_error_scrub() -> None:
    info = scrub_gh_error("gh: Resource not accessible by integration (HTTP 403)", 1)
    ok("gh 403 permission denied", info["permission"] == "denied" and info["http"] == "403")
    ok("gh error has no raw dump fields", "Resource not accessible" not in json.dumps(info))


def test_verify_services_requires_project_match() -> None:
    rows = []
    for line in MULTI_PROJECT_PS.splitlines():
        p = line.split("\t")
        rows.append({"name": p[0], "project": p[1], "service": p[2], "status": p[3], "image": p[4]})
    check = verify_project_services(rows, "sateye-fz2ic4")
    ok("multi-project preview does not satisfy", check["missing_required"] == ["backend", "frontend", "proxy"])


def test_out_dir_rejects_app_tree_and_sets_private_mode() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        app = _prep_app(td_path)
        # OUT inside app must STOP
        bad = app / "out"
        result = run_inventory(
            app_dir=str(app),
            out_dir=str(bad),
            hostname_value="zhzh",
            cmd=MockCmd("happy", app),
            include_runner_checks=False,
        )
        ok("OUT_DIR inside APP_DIR => STOP", result.status == "STOP")

        out = Path("/tmp") / f"e19c-test-{os.getpid()}"
        if out.exists():
            for p in out.glob("*"):
                p.unlink()
            out.rmdir()
        result2 = run_inventory(
            app_dir=str(app),
            out_dir=str(out),
            hostname_value="zhzh",
            cmd=MockCmd("happy", app),
            include_runner_checks=False,
        )
        ok("OUT_DIR under /tmp OK path", result2.status in {"OK", "STOP"})
        if out.exists():
            mode = stat.S_IMODE(out.stat().st_mode)
            ok("OUT_DIR mode 0700", mode == 0o700, detail=oct(mode))
            # cleanup
            for p in out.rglob("*"):
                if p.is_file():
                    p.unlink()
            for p in sorted(out.rglob("*"), reverse=True):
                if p.is_dir():
                    p.rmdir()
            out.rmdir()


def test_secret_scanner_blocks_share() -> None:
    hits = scan_for_secrets("DATABASE_URL=postgresql://user:pass@host/db\n")
    ok("scanner flags connection uri", "connection_uri" in hits)
    hits2 = scan_for_secrets("POSTGRES_PASSWORD=<redacted>\n")
    ok("scanner allows redacted password assignment", hits2 == [])


def test_skip_host_check_rejected_by_shell() -> None:
    import subprocess

    env = os.environ.copy()
    env["SKIP_HOST_CHECK"] = "1"
    env["OUT_DIR"] = f"/tmp/e19c-skip-{os.getpid()}"
    env["APP_DIR"] = "/tmp/nope"
    p = subprocess.run(
        ["bash", str(ROOT / "scripts" / "e19c_operator_inventory.sh")],
        capture_output=True,
        text=True,
        env=env,
    )
    ok("SKIP_HOST_CHECK rejected", p.returncode == 1)
    ok("SKIP_HOST_CHECK message", "SKIP_HOST_CHECK is not supported" in (p.stderr + p.stdout))


def test_missing_evidence_marked_unknown_on_docker_ps_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        app = _prep_app(td_path)
        out = td_path / "out-ps-fail"
        result = run_inventory(
            app_dir=str(app),
            out_dir=str(out),
            hostname_value="zhzh",
            cmd=MockCmd("docker_ps_fail", app),
            include_runner_checks=False,
        )
        ok("docker ps fail => STOP", result.status == "STOP")
        ok("identity not silently passed", result.summary.get("identity_result") == "STOP")


def test_credential_like_metadata_rejected() -> None:
    from e19c_inventory_lib import (
        v_hostname,
        v_docker_name,
        v_git_branch,
        v_image_ref,
        v_mount_dest,
        v_runner_name,
        allowlisted_health_fields,
        parse_docker_ps_lines,
    )

    ok("hostname rejects password URI", v_hostname("host://user:pass@evil") == "UNKNOWN")
    ok("hostname rejects too long", v_hostname("a" * 300) == "UNKNOWN")
    ok(
        "container name rejects credential-like",
        v_docker_name("backend;password=hunter2") == "UNKNOWN",
    )
    ok(
        "git branch with ghp_ => UNKNOWN",
        v_git_branch("feat/ghp_abcdefghijklmnopqrstuvwxyz012345") == "UNKNOWN",
    )
    ok(
        "image ref rejects user:pass@",
        v_image_ref("registry.example/user:SuperSecret@repo/img:latest") == "UNKNOWN",
    )
    ok(
        "mount dest rejects query secret",
        v_mount_dest("/data/imagery?token=abc123secrettoken") == "UNKNOWN",
    )
    ok("runner name rejects token", v_runner_name("runner_token=abc123secrettoken") == "UNKNOWN")
    fields = allowlisted_health_fields(
        '{"status":"healthy password=leak","version":"1.0.0","database":"postgresql"}'
    )
    ok("malformed health status => UNKNOWN", fields.get("status") == "UNKNOWN")

    # docker ps line with credential-like container name dropped
    lines = (
        "sateye-fz2ic4-backend-1\tsateye-fz2ic4\tbackend\tUp\tev-backend:live\n"
        "evil;password=x\tsateye-fz2ic4\tfrontend\tUp\tev-frontend:live\n"
    )
    rows = parse_docker_ps_lines(lines)
    ok("credential-like container row dropped", all(r["name"] != "evil;password=x" for r in rows))
    ok("valid backend row kept", any(r["service"] == "backend" for r in rows))


def test_archive_contains_only_approved_files() -> None:
    import tarfile
    import stat as statmod

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        app = _prep_app(td_path)
        out = Path("/tmp") / f"e19c-arch-{os.getpid()}"
        if out.exists():
            for p in sorted(out.rglob("*"), reverse=True):
                if p.is_file():
                    p.unlink()
                elif p.is_dir():
                    p.rmdir()
            if out.exists():
                out.rmdir()
        result = run_inventory(
            app_dir=str(app),
            out_dir=str(out),
            hostname_value="zhzh",
            cmd=MockCmd("happy", app),
            include_runner_checks=True,
            approved_tip="e3012ce0a26e049d0af981d5994d0d829c3b647e",
        )
        ok("archive path share_safe", result.share_safe is True)
        ok("archive_path set", bool(result.archive_path))
        assert result.archive_path
        ap = Path(result.archive_path)
        ok("archive mode 0600", statmod.S_IMODE(ap.stat().st_mode) == 0o600)
        with tarfile.open(ap, "r:gz") as tar:
            members = sorted(m.name.split("/", 1)[-1] for m in tar.getmembers() if m.isfile())
        from e19c_inventory_lib import APPROVED_ARCHIVE_FILES

        ok("archive members subset of approved", set(members) <= APPROVED_ARCHIVE_FILES)
        ok("summary in archive", "00_return_summary.txt" in members)
        ok("manifest in archive", "15_manifest.txt" in members)
        ok("STOP files not in archive", "STOP.txt" not in members and "STOP_SECRETS.txt" not in members)
        # cleanup
        ap.unlink(missing_ok=True)
        for p in sorted(out.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                p.rmdir()
        if out.exists():
            out.rmdir()


def test_malformed_values_never_written_as_literals() -> None:
    from e19c_inventory_lib import v_hostname, v_git_sha, v_image_id, v_http_code

    ok("newline hostname UNKNOWN", v_hostname("zhzh\npassword=x") == "UNKNOWN")
    ok("short git sha ok", v_git_sha("1e71b7a") != "UNKNOWN")
    ok("invalid git sha UNKNOWN", v_git_sha("ZZZZZZZ") == "UNKNOWN")
    ok("invalid image id UNKNOWN", v_image_id("sha256:deadbeef") == "UNKNOWN")
    ok("http 200 ok", v_http_code("200") == "200")
    ok("http garbage UNKNOWN", v_http_code("200 OK password=x") == "UNKNOWN")


def main() -> int:
    test_compose_structure_allowlist()
    test_health_allowlist()
    test_gh_error_scrub()
    test_verify_services_requires_project_match()
    test_secret_scanner_blocks_share()
    test_wrong_host_stops_without_inventory()
    test_project_exists_but_required_services_on_other_project_stops()
    test_incomplete_required_services_stops()
    test_secrets_never_appear_in_shared_outputs()
    test_out_dir_rejects_app_tree_and_sets_private_mode()
    test_skip_host_check_rejected_by_shell()
    test_missing_evidence_marked_unknown_on_docker_ps_fail()
    test_credential_like_metadata_rejected()
    test_archive_contains_only_approved_files()
    test_malformed_values_never_written_as_literals()
    print(f"\nRESULT pass={PASS} fail={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
