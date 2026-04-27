"""Entry point: ``python -m blackjack.run_server``."""

from __future__ import annotations

import logging
import os
import signal
import sys

from .server.server import DEFAULT_HOST, DEFAULT_PORT, BlackjackServer


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

    def _stop(_signum, _frame) -> None:
        server.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
