"""Entry point for `python -m ceo`."""

from ceo.logging_config import setup_logging
from ceo.tui.app import CeoApp


def main() -> None:
    setup_logging()
    app = CeoApp()
    app.run()


if __name__ == "__main__":
    main()
