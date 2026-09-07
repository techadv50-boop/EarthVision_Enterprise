# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ServerBackup.exe (build on Windows)."""

from pathlib import Path

from PyInstaller.building.api import EXE, PYZ
from PyInstaller.building.build_main import Analysis

# SPECPATH is the directory containing this spec file (ServerBackup/).
root = Path(SPECPATH).resolve()
if not (root / "app" / "main.py").is_file():
    root = root.parent

a = Analysis(
    [str(root / "app" / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "config" / "default.json"), "config"),
        (str(root / "scripts"), "scripts"),
    ],
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "app.gui",
        "app.gui.main_window",
        "app.gui.settings_page",
        "app.gui.setup_dialog",
        "app.gui.folders",
        "app.gui.history_page",
        "app.gui.logs_page",
        "app.gui.restore_page",
        "app.gui.security_page",
        "app.gui.styles",
        "app.gui.widgets",
        "app.engine.backup_engine",
        "app.serversec.engine",
        "app.restore.restore_engine",
        "app.scheduler.tasks",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ServerBackup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
