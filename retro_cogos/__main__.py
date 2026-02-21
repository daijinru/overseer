"""Entry point for `python -m retro_cogos`."""

from retro_cogos.logging_config import setup_logging
from retro_cogos.tui.app import RetroCogosApp


def main() -> None:
    setup_logging()
    app = RetroCogosApp()
    app.run()


if __name__ == "__main__":
    main()
