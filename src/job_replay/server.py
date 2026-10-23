"""Small localhost-only HTTP app for recording and replaying listing snapshots."""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from job_replay.career_ops import import_postings
from job_replay.storage import ReplayStore

MAX_REQUEST_BYTES = 5 * 1024 * 1024


def make_handler(store: ReplayStore) -> type[BaseHTTPRequestHandler]:
    class ReplayHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if not self._local_host():
                self._json(403, {"error": "only local requests are allowed"})
                return
            path = urlsplit(self.path).path
            if path == "/":
                web_page = Path(__file__).parent / "web" / "index.html"
                self._send(200, web_page.read_bytes(), "text/html; charset=utf-8")
                return
            if path in {"/app.css", "/app.js", "/favicon.svg"}:
                asset = Path(__file__).parent / "web" / path.removeprefix("/")
                content_types = {
                    "/app.css": "text/css; charset=utf-8",
                    "/app.js": "text/javascript; charset=utf-8",
                    "/favicon.svg": "image/svg+xml",
                }
                content_type = content_types[path]
                self._send(200, asset.read_bytes(), content_type)
                return
            if path == "/api/listings":
                self._json(200, {"listings": store.list_listings()})
                return
            if path == "/api/export":
                self._json(200, store.export_data())
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
            if not self._local_host():
                self._json(403, {"error": "only local requests are allowed"})
                return
            path = urlsplit(self.path).path
            if path not in {"/api/snapshots", "/api/import"}:
                self._json(404, {"error": "not found"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(400, {"error": "invalid Content-Length"})
                return
            if length <= 0 or length > MAX_REQUEST_BYTES:
                self._json(413, {"error": "request body must be between 1 byte and 5 MiB"})
                return

            try:
                data = json.loads(self.rfile.read(length))
                if path == "/api/import":
                    result = store.import_data(data)
                    self._json(200, result)
                    return
                listing, changed = store.record_snapshot(data)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
                self._json(400, {"error": str(error)})
                return
            self._json(201 if changed else 200, {"changed": changed, "listing": listing})

        def do_DELETE(self) -> None:
            if not self._local_host():
                self._json(403, {"error": "only local requests are allowed"})
                return
            path = urlsplit(self.path).path
            if not path.startswith("/api/listings/"):
                self._json(404, {"error": "not found"})
                return
            raw_id = path.removeprefix("/api/listings/")
            if not raw_id.isdecimal():
                self._json(400, {"error": "listing id must be a positive integer"})
                return
            if not store.delete_listing(int(raw_id)):
                self._json(404, {"error": "listing not found"})
                return
            self._json(200, {"deleted": True})

        def _json(self, status: int, value: object) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _local_host(self) -> bool:
            try:
                hostname = urlsplit(f"//{self.headers.get('Host', '')}").hostname
            except ValueError:
                return False
            return hostname in {"localhost", "127.0.0.1", "::1"}

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                "img-src 'self' data:; font-src 'self'; object-src 'none'; base-uri 'none'; "
                "frame-ancestors 'none'",
            )
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
    parser = argparse.ArgumentParser(description="Run the local Job Search Replay app.")
    parser.add_argument("--port", type=int, default=8000, help="local HTTP port (default: 8000)")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(
            os.environ.get("JOB_REPLAY_DB", Path.home() / ".job-replay" / "replay.sqlite3")
        ),
        help="SQLite database path (default: JOB_REPLAY_DB or ~/.job-replay/replay.sqlite3)",
    )
    parser.add_argument(
        "--import-career-ops",
        type=Path,
        metavar="DATABASE",
        help="import discovered postings from a career-ops SQLite database, then exit",
    )
    arguments = parser.parse_args()
    if not 1 <= arguments.port <= 65_535:
        parser.error("--port must be between 1 and 65535")
    database_path = arguments.database
    if arguments.import_career_ops:
        try:
            store = ReplayStore(database_path)
            result = import_postings(arguments.import_career_ops, store)
        except ValueError as error:
            parser.error(str(error))
        print(
            f"career-ops import complete: {result['imported']} snapshots added, "
            f"{result['skipped']} duplicates skipped."
        )
        print(f"Replay database: {database_path}")
        return
    server = create_server(database_path, port=arguments.port)
    print(f"Job Search Replay is running at http://{server.server_address[0]}:{server.server_address[1]}")
    print(f"Database: {database_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Job Search Replay.")
    finally:
        server.server_close()
