# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for building retro-cogos single-file binary."""

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

hiddenimports = [
    "retro_cogos.cli",
    "retro_cogos.config",
    "retro_cogos.database",
    "retro_cogos.models",
    "retro_cogos.models.cognitive_object",
    "retro_cogos.models.execution",
    "retro_cogos.models.memory",
    "retro_cogos.models.artifact",
    "retro_cogos.services",
    "retro_cogos.tui",
]
hiddenimports += collect_submodules("rich")
hiddenimports += collect_submodules("textual")

datas = [
    ("retro_cogos/config.cp.yaml", "retro_cogos/"),
    ("retro_cogos/tui/styles/app.tcss", "retro_cogos/tui/styles/"),
]
datas += collect_data_files("rich")
datas += collect_data_files("textual")

a = Analysis(
    ["retro_cogos/__main__.py"],
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
    name="retro-cogos",
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
