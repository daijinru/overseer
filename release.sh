#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "==> Syncing dependencies (including dev group)..."
uv sync --group dev

echo "==> Building binary with PyInstaller..."
uv run pyinstaller retro_cogos.spec --noconfirm

echo ""
echo "==> Build complete: dist/retro-cogos"
echo "    Run ./dist/retro-cogos init to initialize config."
