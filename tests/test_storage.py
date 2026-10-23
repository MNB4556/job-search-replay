import json
import tempfile
import unittest
from pathlib import Path

from job_replay.storage import ReplayStore


class ReplayStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ReplayStore(Path(self.temp_dir.name) / "replay.sqlite3")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_first_capture_creates_listing_and_snapshot(self) -> None:
        listing, changed = self.store.record_snapshot(
            {"title": "Engineer", "company": "Example", "url": "https://jobs.example/role/"}
        )

        self.assertTrue(changed)
        self.assertEqual(listing["snapshot_count"], 1)
        self.assertEqual(listing["title"], "Engineer")
        self.assertEqual(len(listing["snapshots"]), 1)

    def test_same_url_with_changes_adds_replayable_snapshot(self) -> None:
        first, _ = self.store.record_snapshot(
            {"title": "Engineer", "company": "Example", "url": "https://jobs.example/role"}
        )
        second, changed = self.store.record_snapshot(
            {
                "title": "Senior Engineer",
                "company": "Example",
                "url": "https://jobs.example/role/",
                "salary": "£60,000",
            }
        )

        self.assertTrue(changed)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["snapshot_count"], 2)
        self.assertEqual(second["snapshots"][0]["title"], "Engineer")
        self.assertEqual(second["snapshots"][1]["salary"], "£60,000")

    def test_identical_capture_does_not_duplicate_snapshot(self) -> None:
        payload = {"title": "Engineer", "company": "Example", "url": "https://jobs.example/role"}
        first, _ = self.store.record_snapshot(payload)
        second, changed = self.store.record_snapshot(payload)

        self.assertFalse(changed)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["snapshot_count"], 1)

    def test_missing_url_matches_identity_across_case_and_whitespace(self) -> None:
        first, _ = self.store.record_snapshot({"title": "Engineer", "company": "Example Co"})
        second, changed = self.store.record_snapshot(
            {"title": "  ENGINEER ", "company": " example   co "}
        )

        self.assertTrue(changed)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["snapshot_count"], 2)

    def test_invalid_capture_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "title is required"):
            self.store.record_snapshot({"company": "Example"})
        with self.assertRaisesRegex(ValueError, "http or https"):
            self.store.record_snapshot(
                {"title": "Engineer", "company": "Example", "url": "javascript:alert(1)"}
            )

    def test_unknown_listing_returns_none(self) -> None:
        self.assertIsNone(self.store.get_listing(1))

    def test_export_import_preserves_history_and_skips_duplicates(self) -> None:
        self.store.record_snapshot(
            {"title": "Engineer", "company": "Example", "url": "https://jobs.example/role"}
        )
        self.store.record_snapshot(
            {
                "title": "Senior Engineer",
                "company": "Example",
                "url": "https://jobs.example/role",
                "salary": "£60,000",
            }
        )
        backup = self.store.export_data()

        restored = ReplayStore(Path(self.temp_dir.name) / "restored.sqlite3")
        first_import = restored.import_data(backup)
        second_import = restored.import_data(backup)
        result = restored.list_listings()[0]

        self.assertEqual(first_import, {"imported": 2, "skipped": 0})
        self.assertEqual(second_import, {"imported": 0, "skipped": 2})
        self.assertEqual(result["snapshot_count"], 2)
        self.assertEqual(result["title"], "Senior Engineer")

    def test_invalid_import_does_not_partially_write(self) -> None:
        backup = {
            "format": "job-search-replay",
            "version": 1,
            "listings": [
                {
                    "snapshots": [
                        {
                            "title": "Engineer",
                            "company": "Example",
                            "captured_at": "2026-01-01T00:00:00+00:00",
                        }
                    ]
                },
                {"snapshots": [{"company": "Missing title"}]},
            ],
        }

        with self.assertRaisesRegex(ValueError, "title is required"):
            self.store.import_data(backup)
        self.assertEqual(self.store.list_listings(), [])

    def test_delete_listing_removes_its_history(self) -> None:
        listing, _ = self.store.record_snapshot({"title": "Engineer", "company": "Example"})

        self.assertTrue(self.store.delete_listing(listing["id"]))
        self.assertFalse(self.store.delete_listing(listing["id"]))
        self.assertIsNone(self.store.get_listing(listing["id"]))

    def test_public_demo_backup_imports_as_three_fictional_roles(self) -> None:
        path = Path(__file__).resolve().parents[1] / "examples" / "demo-backup.json"
        backup = json.loads(path.read_text(encoding="utf-8"))

        result = self.store.import_data(backup)
        listings = self.store.list_listings()

        self.assertEqual(result, {"imported": 6, "skipped": 0})
        self.assertEqual(len(listings), 3)
        self.assertEqual(sum(listing["snapshot_count"] for listing in listings), 6)
        self.assertEqual(
            self.store.import_data(backup), {"imported": 0, "skipped": 6}
        )


if __name__ == "__main__":
    unittest.main()
