#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

uv sync --quiet
exec uv run python -m ceo
