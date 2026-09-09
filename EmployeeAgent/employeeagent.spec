# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for EmployeeAgent.exe (build on Windows)."""

from pathlib import Path

from PyInstaller.building.api import EXE, PYZ
from PyInstaller.building.build_main import Analysis

root = Path(SPECPATH).resolve()
if not (root / "app" / "main.py").is_file():
    root = root.parent

a = Analysis(
    [str(root / "app" / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "app.gui",
        "app.gui.app",
        "app.gui.dashboard",
        "app.gui.tray",
        "app.gui.styles",
        "app.gui.password_dialog",
        "app.gui.setup_dialog",
        "app.gui.native",
        "app.gui.already_running",
        "app.service.agent",
        "app.platform.windows",
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
    name="EmployeeAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=None,
)
