"""CLI entry point for Retro CogOS."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click

BANNER = """\
╔══════════════════════════════════════╗
║  RETRO COGOS - Cognitive Operating   ║
║  System Initialization               ║
╚══════════════════════════════════════╝"""

VERSION = "0.1.0"


def _find_template() -> Path:
    """Locate config.cp.yaml, supporting both dev and PyInstaller."""
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / "retro_cogos" / "config.cp.yaml"
    return Path(__file__).parent / "config.cp.yaml"


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """RETRO COGOS - Cognitive Operating System"""
    if ctx.invoked_subcommand is None:
        ctx.invoke(run)


@cli.command()
def run() -> None:
    """Start the Retro CogOS TUI."""
    from retro_cogos.config import load_config
    from retro_cogos.logging_config import setup_logging
    from retro_cogos.tui.app import RetroCogosApp

    load_config()
    setup_logging()
    app = RetroCogosApp()
    app.run()


@cli.command()
@click.option("--force", is_flag=True, help="Overwrite existing config file.")
def init(force: bool) -> None:
    """Initialize config to ~/.retro_cogos/."""
    from retro_cogos.config import _default_data_dir

    config_dir = _default_data_dir()
    config_dest = config_dir / "config.yaml"
    template = _find_template()

    click.echo(BANNER)
    click.echo()

    # Create base directory
    config_dir.mkdir(parents=True, exist_ok=True)
    click.echo(f"  [ok] Directory ready: {config_dir}")

    # Copy config template
    if config_dest.exists() and not force:
        click.echo(f"  [--] Config already exists: {config_dest}")
        click.echo("       Use --force to overwrite.")
    else:
        shutil.copy2(template, config_dest)
        click.echo(f"  [ok] Config created: {config_dest}")

    # Create subdirectories
    for subdir in ["logs", "output"]:
        p = config_dir / subdir
        p.mkdir(parents=True, exist_ok=True)
        click.echo(f"  [ok] Subdirectory ready: {p}")

    click.echo()
    click.echo(f"  -> Edit {config_dest} to set your API key.")
    click.echo("  -> Then run `retro-cogos` to start the system.")


@cli.command()
def version() -> None:
    """Show version information."""
    click.echo(f"retro-cogos v{VERSION}")
