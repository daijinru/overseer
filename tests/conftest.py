"""Shared test fixtures."""

from __future__ import annotations

import os
import tempfile

import pytest

from retro_cogos.config import AppConfig, reset_config, load_config
from retro_cogos.database import Base, reset_db, get_engine, init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    """Use an in-memory SQLite database for each test."""
    reset_config()
    reset_db()

    # Write a temporary config pointing to tmp db
    db_path = str(tmp_path / "test.db")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        f"llm:\n  base_url: http://localhost:0\n  api_key: test-key\n  model: test\n"
        f"database:\n  path: {db_path}\n"
        f"context:\n  output_dir: {tmp_path / 'output'}\n"
        f"tool_permissions:\n  file_read: auto\n  web_search: auto\n  file_write: confirm\n  file_delete: approve\n  default: confirm\n"
    )

    os.chdir(tmp_path)
    load_config(config_file)
    init_db()
    yield tmp_path

    reset_db()
    reset_config()
