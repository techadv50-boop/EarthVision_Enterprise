import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from app.heartbeat.client import HeartbeatClient
from app.heartbeat.protocol import ALLOWED_HEARTBEAT_FIELDS, HEARTBEAT_PATH, build_heartbeat_payload
from app.status.events import CONN_UNAVAILABLE
from tests.conftest import build_service
from tests.helpers import types
from app.heartbeat.client import FakeHeartbeat


def test_heartbeat_payload_is_presence_only(clock):
    payload = build_heartbeat_payload(
        employee_id="12",
        device_id="EMP12-PC",
        employee_status="ACTIVE",
        activity_status="ACTIVE",
        connection_status="CONNECTED",
        timestamp=clock.now(),
        last_input_age_seconds=1.5,
        boot_id="boot-1",
    )
    assert set(payload) <= ALLOWED_HEARTBEAT_FIELDS
    assert "keystrokes" not in payload
    assert "mouse" not in json.dumps(payload)


def test_heartbeat_client_posts_to_fastapi_path(tmp_path, clock, platform, password):
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            received["path"] = self.path
            received["body"] = json.loads(self.rfile.read(length))
            self.send_response(204)
            self.end_headers()

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        service = build_service(tmp_path, clock, platform, password, logged_in=True)
        client = HeartbeatClient(url, clock=clock)
        service.start()
        result = client.send(service.engine)
        assert result.ok
        assert received["path"] == HEARTBEAT_PATH
        assert received["body"]["employee_id"] == "12"
        assert received["body"]["device_id"] == "EMP12-PC"
    finally:
        server.shutdown()


def test_missed_heartbeats_mark_offline_not_inactive(tmp_path, clock, platform, password):
    heartbeat = FakeHeartbeat(succeed=False, clock=clock)
    service = build_service(tmp_path, clock, platform, password, heartbeat=heartbeat, logged_in=True)
    platform.idle = 0
    service.start()
    service.tick()
    assert service.engine.state.activity_status() == "ACTIVE"
    clock.advance(30)
    service.tick()
    assert service.engine.state.connection == CONN_UNAVAILABLE
    assert service.engine.state.employee_status() == "OFFLINE"
    assert service.engine.state.activity_status() == "ACTIVE"
    assert "INACTIVE" not in types(service)
    assert "OFFLINE" in types(service)
