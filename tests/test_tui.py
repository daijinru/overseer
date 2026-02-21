"""Basic TUI tests — Phase 7 verification."""

import pytest

from retro_cogos.config import load_config, reset_config
from retro_cogos.database import init_db, reset_db


@pytest.fixture
def app_env(tmp_path):
    """Set up environment for TUI tests."""
    import os

    reset_config()
    reset_db()

    db_path = str(tmp_path / "test.db")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        f"llm:\n  base_url: http://localhost:0\n  api_key: test\n  model: test\n"
        f"database:\n  path: {db_path}\n"
        f"context:\n  output_dir: {tmp_path / 'output'}\n"
    )
    os.chdir(tmp_path)
    load_config(config_file)
    init_db()
    yield tmp_path
    reset_db()
    reset_config()


@pytest.mark.asyncio
async def test_app_starts(app_env):
    """App should start and show the home screen."""
    from retro_cogos.tui.app import RetroCogosApp

    app = RetroCogosApp()
    async with app.run_test(size=(80, 24)) as pilot:
        assert pilot.app.title == "RETRO COGOS v2.0.76"
        assert len(pilot.app.screen_stack) >= 1
