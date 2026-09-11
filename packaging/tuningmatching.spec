# -*- mode: python ; coding: utf-8 -*-
# PyInstaller-spec voor TuningMatching (Windows 10/11, geen Python vereist).
# Bouwen:  pyinstaller packaging/tuningmatching.spec --noconfirm
# Resultaat: dist/TuningMatching/TuningMatching.exe (portable map)
#            optioneel: Inno Setup (packaging/installer.iss) → TuningMatchingSetup.exe

import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
hidden = collect_submodules('app') + [
    'uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on',
    'anyio._backends._asyncio',
]

a = Analysis(
    ['../app/__main__.py'],
    pathex=['..'],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'notebook', 'pytest'],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='TuningMatching',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # CLI-uitvoer zichtbaar; GUI start in eigen venster
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name='TuningMatching',
)
