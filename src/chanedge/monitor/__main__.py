"""python -m chanedge.monitor --db data/chanedge.sqlite --port 8765"""

from __future__ import annotations

import argparse
import sys

from chanedge.monitor.server import LOOPBACK, build_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chanedge monitor")
    parser.add_argument("--db", required=True)
    parser.add_argument("--host", default=LOOPBACK)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        server = build_server(args.db, host=args.host, port=args.port)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"monitor on http://{args.host}:{server.server_address[1]}/ (read-only)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
