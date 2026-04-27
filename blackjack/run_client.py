"""Entry point: ``python -m blackjack.run_client``."""

from __future__ import annotations

import logging
import os

from .client.gui import AppController


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    host = os.environ.get("BJ_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("BJ_PORT", "5050"))
    except ValueError:
        port = 5050
    AppController(host=host, port=port).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
