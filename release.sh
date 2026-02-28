#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "==> Syncing dependencies (including dev group)..."
uv sync --group dev

echo "==> Building binary with PyInstaller..."
uv run pyinstaller overseer.spec --noconfirm

echo ""
echo "==> Build complete: dist/overseer"
echo "    Run ./dist/overseer init to initialize config."
