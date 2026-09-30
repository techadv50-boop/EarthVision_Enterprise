# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for WebCrawler Enterprise (Windows standalone GUI)."""

import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

datas = []
binaries = []
hiddenimports = [
    "playwright",
    "playwright.sync_api",
    "bs4",
    "lxml",
    "httpx",
    "pdfplumber",
    "fitz",
    "docx",
    "openpyxl",
    "phonenumbers",
    "tldextract",
    "PySide6",
    "shiboken6",
    "webcrawler",
    "webcrawler.runtime",
    "webcrawler.scanner",
    "webcrawler.scanner.folder_scanner",
    "PIL",
    "pytesseract",
]

for pkg in ("PySide6", "shiboken6", "playwright", "tldextract", "phonenumbers", "certifi"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception as exc:
        print(f"collect_all({pkg}) warning: {exc}", file=sys.stderr)

try:
    hiddenimports += collect_submodules("webcrawler")
except Exception:
    pass

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WebCrawlerEnterprise",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="WebCrawlerEnterprise",
)
