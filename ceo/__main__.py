"""Entry point for `python -m ceo`."""

from ceo.tui.app import CeoApp


def main() -> None:
    app = CeoApp()
    app.run()


if __name__ == "__main__":
    main()
