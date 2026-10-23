"""Small localhost-only HTTP app for recording and replaying listing snapshots."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from job_replay.storage import ReplayStore

MAX_REQUEST_BYTES = 64 * 1024
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def make_handler(store: ReplayStore) -> type[BaseHTTPRequestHandler]:
    class ReplayHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/":
                web_page = Path(__file__).parent / "web" / "index.html"
                self._send(200, web_page.read_bytes(), "text/html; charset=utf-8")
                return
            if path == "/api/listings":
                self._json(200, {"listings": store.list_listings()})
                return
            if path.startswith("/api/listings/"):
                raw_id = path.removeprefix("/api/listings/")
                if not raw_id.isdecimal():
                    self._json(400, {"error": "listing id must be a positive integer"})
                    return
                listing = store.get_listing(int(raw_id))
                if listing is None:
                    self._json(404, {"error": "listing not found"})
                    return
                self._json(200, listing)
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/api/snapshots":
                self._json(404, {"error": "not found"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(400, {"error": "invalid Content-Length"})
                return
            if length <= 0 or length > MAX_REQUEST_BYTES:
                self._json(413, {"error": "request body must be between 1 byte and 64 KiB"})
                return

            try:
                data = json.loads(self.rfile.read(length))
                listing, changed = store.record_snapshot(data)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
                self._json(400, {"error": str(error)})
                return
            self._json(201 if changed else 200, {"changed": changed, "listing": listing})

        def _json(self, status: int, value: object) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            print(f"{self.address_string()} - {format % args}")

    return ReplayHandler


def create_server(
    database_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> ThreadingHTTPServer:
    store = ReplayStore(database_path)
    return ThreadingHTTPServer((host, port), make_handler(store))


def main() -> None:
    database_path = Path(os.environ.get("JOB_REPLAY_DB", PROJECT_ROOT / "data" / "replay.sqlite3"))
    server = create_server(database_path)
    print(f"Job Search Replay is running at http://{server.server_address[0]}:{server.server_address[1]}")
    print(f"Database: {database_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Job Search Replay.")
    finally:
        server.server_close()
