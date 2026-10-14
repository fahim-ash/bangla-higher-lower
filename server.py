#!/usr/bin/env python3
"""Serve the game. /items.json is read live from the SQLite DB.

  python3 server.py [port]     (default 8000)
"""
import functools
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import db

STATIC = os.path.join(db.ROOT, "static")


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] == "/items.json":
            conn = db.connect()
            try:
                body = json.dumps(db.all_items(conn), ensure_ascii=False).encode("utf-8")
            finally:
                conn.close()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("0.0.0.0", port), functools.partial(Handler, directory=STATIC))
    print(f"Higher Lower: Bangladesh edition → http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
