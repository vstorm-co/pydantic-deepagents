"""Run the gateway: ``python -m apps.gateway``.

Binds to loopback, generates a bearer token, and prints a single line of JSON
(``{"port": ..., "token": ...}``) to stdout so a parent process (the desktop
shell) can connect. All other logging goes to stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from apps.gateway.app import create_app
from apps.gateway.auth import generate_token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apps.gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 = let the OS pick a free port")
    parser.add_argument(
        "--token",
        default=os.environ.get("PYDANTIC_DEEP_GATEWAY_TOKEN"),
        help="Bearer token (else generated; also read from env)",
    )
    args = parser.parse_args(argv)

    import socket

    import uvicorn

    token = args.token or generate_token()
    app = create_app(token=token)

    # Resolve the actual port up-front so we can advertise it before serving.
    port = args.port
    if port == 0:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((args.host, 0))
        port = sock.getsockname()[1]
        sock.close()

    sys.stdout.write(json.dumps({"port": port, "token": token}) + "\n")
    sys.stdout.flush()

    uvicorn.run(app, host=args.host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
