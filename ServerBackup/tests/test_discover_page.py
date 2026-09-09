from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.discover.approval import application_id, split_approval_applications
from app.discover.policy import apply_policy, load_policy
from tests.helpers import make_config
from tests.test_approval import live_shaped_apps

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QMessageBox, QPushButton  # noqa: E402

from app.gui.discover_page import DiscoverPage  # noqa: E402
from app.gui.main_window import MainWindow  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def test_discover_page_shows_checkboxes_and_required_buttons(tmp_path: Path):
    qt = _app()
    cfg = make_config(tmp_path)
    Path(cfg.backup_destination).mkdir(parents=True, exist_ok=True)
    page = DiscoverPage()
    page.reload(cfg, {"applications": live_shaped_apps()})
    page.show()
    qt.processEvents()
    assert page.findChild(QPushButton, "approveSelected") is not None
    assert page.findChild(QPushButton, "approveAll") is not None
    assert page.findChild(QPushButton, "cancelApproval") is not None
    checks = page.findChildren(QCheckBox, "applicationCheck")
    enabled = [box for box in checks if box.isEnabled()]
    assert [box.property("application_id") for box in enabled] == [
        "wordpress:/var/www/50sea.com",
        "ojs:/var/www/journal.50sea.com",
        "ojs:/var/www/journal.xdgen.com",
        "php:/var/www/xdgen.com",
    ]
    assert all(not box.isChecked() for box in enabled)
    labels = "\n".join(label.text() for label in page.findChildren(QLabel))
    assert "OJS files: /var/lib/ojs-journal50" in labels
    assert "OJS files: /var/www/ojs-files" in labels
    assert "MariaDB sea_tecdb" in labels
    assert "[EXCLUDED]" in labels
    assert "other:/var/www/html" in labels
    assert "UNUSED DEFAULT ROOT" in labels
    html_boxes = [box for box in checks if box.property("application_id") == "other:/var/www/html"]
    assert html_boxes
    assert all(not box.isEnabled() for box in html_boxes)
    page.close()


def test_discover_page_approve_all_skips_html_and_does_not_backup(tmp_path: Path, monkeypatch):
    qt = _app()
    cfg = make_config(tmp_path)
    Path(cfg.backup_destination).mkdir(parents=True, exist_ok=True)
    page = DiscoverPage()
    emitted: list[int] = []
    page.approved.connect(emitted.append)
    page.reload(cfg, {"applications": live_shaped_apps()})
    page.show()
    qt.processEvents()
    monkeypatch.setattr(
        "app.gui.discover_page.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    page._approve_all()
    qt.processEvents()
    assert emitted == [4]
    policy = load_policy(cfg.backup_destination)
    apps = policy.get("applications") or {}
    assert apps["wordpress:/var/www/50sea.com"]["approved"] is True
    assert "other:/var/www/html" not in apps or not apps.get("other:/var/www/html", {}).get("approved")
    pending, included, excluded = split_approval_applications(page._rows)
    assert len(included) == 4
    assert pending == []
    assert application_id(excluded[0]) == "other:/var/www/html"
    page.close()


def test_discover_page_approve_selected_only_checked_rows(tmp_path: Path):
    qt = _app()
    cfg = make_config(tmp_path)
    Path(cfg.backup_destination).mkdir(parents=True, exist_ok=True)
    page = DiscoverPage()
    emitted: list[int] = []
    page.approved.connect(emitted.append)
    page.reload(cfg, {"applications": live_shaped_apps()})
    page.show()
    qt.processEvents()
    enabled = [box for box in page.findChildren(QCheckBox, "applicationCheck") if box.isEnabled()]
    enabled[0].setChecked(True)
    enabled[1].setChecked(True)
    page._approve_selected()
    qt.processEvents()
    assert emitted == [2]
    policy = load_policy(cfg.backup_destination)
    apps = policy.get("applications") or {}
    assert apps["wordpress:/var/www/50sea.com"]["approved"] is True
    assert apps["ojs:/var/www/journal.50sea.com"]["approved"] is True
    assert "php:/var/www/xdgen.com" not in apps
    page.close()


def test_main_window_review_button_opens_approval_view(tmp_path: Path):
    qt = _app()
    cfg = make_config(tmp_path)
    Path(cfg.backup_destination).mkdir(parents=True, exist_ok=True)
    from app.discover.policy import save_snapshot, snapshot_application_row

    save_snapshot(
        cfg.backup_destination,
        {"applications": [snapshot_application_row(row) for row in apply_policy(live_shaped_apps(), cfg.backup_destination)]},
    )
    window = MainWindow(cfg, ssh_password="in-memory")
    window.timer.stop()
    window.show()
    qt.processEvents()
    assert window.dashboard.review_apps_button.text() == "REVIEW / APPROVE APPLICATIONS"
    window.show_discover()
    qt.processEvents()
    assert window.stack.currentWidget() is window.discover_page
    assert window.discover_page.findChild(QPushButton, "approveAll") is not None
    window.close()
