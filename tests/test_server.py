import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from job_replay.server import create_server


class ReplayServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = create_server(Path(self.temp_dir.name) / "replay.sqlite3", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp_dir.cleanup()

    def request(
        self,
        method: str,
        path: str,
        data: object | None = None,
        headers: dict[str, str] | None = None,
    ):
        connection = HTTPConnection(self.host, self.port)
        body = json.dumps(data) if data is not None else None
        request_headers = {"Content-Type": "application/json"} if body else {}
        request_headers.update(headers or {})
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        content = response.read()
        self.last_headers = dict(response.getheaders())
        connection.close()
        return response.status, response.getheader("Content-Type"), content

    def test_homepage_and_api_capture(self) -> None:
        status, content_type, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertTrue(content_type.startswith("text/html"))
        self.assertIn(b"Keep the story.", page)
        self.assertEqual(self.last_headers.get("Cache-Control"), "no-store")
        csp = self.last_headers.get("Content-Security-Policy", "")
        self.assertIn("frame-ancestors 'none'", csp)

        status, content_type, stylesheet = self.request("GET", "/app.css")
        self.assertEqual(status, 200)
        self.assertTrue(content_type.startswith("text/css"))
        self.assertIn(b"prefers-reduced-motion", stylesheet)

        status, _, body = self.request(
            "POST",
            "/api/snapshots",
            {"title": "Engineer", "company": "Example"},
        )
        result = json.loads(body)
        self.assertEqual(status, 201)
        self.assertTrue(result["changed"])

        status, _, body = self.request("GET", "/api/listings")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["listings"]), 1)

    def test_export_import_and_delete_endpoints(self) -> None:
        _, _, saved = self.request(
            "POST", "/api/snapshots", {"title": "Engineer", "company": "Example"}
        )
        listing_id = json.loads(saved)["listing"]["id"]
        status, _, backup = self.request("GET", "/api/export")
        self.assertEqual(status, 200)

        other_store = Path(self.temp_dir.name) / "other.sqlite3"
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.server = create_server(other_store, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

        status, _, imported = self.request("POST", "/api/import", json.loads(backup))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(imported), {"imported": 1, "skipped": 0})
        status, _, deleted = self.request("DELETE", f"/api/listings/{listing_id}")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(deleted)["deleted"])

    def test_invalid_capture_returns_client_error(self) -> None:
        status, _, body = self.request("POST", "/api/snapshots", {"company": "Example"})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "title is required")

    def test_missing_listing_returns_not_found(self) -> None:
        status, _, body = self.request("GET", "/api/listings/999")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "listing not found")

    def test_non_local_host_header_is_rejected(self) -> None:
        status, _, body = self.request("GET", "/", headers={"Host": "replay.attacker.example"})
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"], "only local requests are allowed")


if __name__ == "__main__":
    unittest.main()
