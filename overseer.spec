# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for building overseer single-file binary."""

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

hiddenimports = [
    "overseer.cli",
    "overseer.config",
    "overseer.database",
    "overseer.models",
    "overseer.models.cognitive_object",
    "overseer.models.execution",
    "overseer.models.memory",
    "overseer.models.artifact",
    "overseer.services",
    "overseer.tui",
]
hiddenimports += collect_submodules("rich")
hiddenimports += collect_submodules("textual")

datas = [
    ("overseer/config.cp.yaml", "overseer/"),
    ("overseer/tui/styles/app.tcss", "overseer/tui/styles/"),
]
datas += collect_data_files("rich")
datas += collect_data_files("textual")

a = Analysis(
    ["overseer/__main__.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="overseer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
