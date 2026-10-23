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


if __name__ == "__main__":
    unittest.main()
