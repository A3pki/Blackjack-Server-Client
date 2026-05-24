"""Entry point: ``python -m blackjack.run_server_gui``."""

from __future__ import annotations

import logging
import os
import sys

from .server.server import DEFAULT_HOST, DEFAULT_PORT, BlackjackServer
from .server.gui import ServerApp


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    host = os.environ.get("BJ_HOST", DEFAULT_HOST)
    try:
        port = int(os.environ.get("BJ_PORT", str(DEFAULT_PORT)))
    except ValueError:
        print("BJ_PORT must be an integer", file=sys.stderr)
        return 2

    server = BlackjackServer(host=host, port=port)
    app = ServerApp(server=server, host=host, port=port)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
