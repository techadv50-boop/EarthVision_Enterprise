# -*- mode: python ; coding: utf-8 -*-
# Standalone desktop-only build (no web server / no browser UI)

block_cipher = None

a = Analysis(
    ['DOI_REDIF_Standalone.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'app.gui',
        'app.extractor',
        'app.redif',
        'app.models',
        'app.report',
        'app.paths',
        'openpyxl',
        'bs4',
        'lxml',
        'lxml.etree',
        'httpx',
        'certifi',
        'tkinter',
        '_tkinter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pytest',
        'pytest_asyncio',
        'uvicorn',
        'fastapi',
        'starlette',
        'multipart',
        'webbrowser',
        'app.main',
        'app.jobs',
        'app.desktop',
        'app.cli',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DOI_URL_REDIF_Standalone',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # pure desktop window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
