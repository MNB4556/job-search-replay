import io
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from job_replay.career_ops import import_postings
from job_replay.server import main
from job_replay.storage import ReplayStore


class CareerOpsImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database = self.root / "career-ops.sqlite3"
        self.store = ReplayStore(self.root / "replay.sqlite3")
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE postings (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    url TEXT,
                    source TEXT,
                    location TEXT,
                    salary TEXT,
                    salary_min INTEGER,
                    salary_max INTEGER,
                    salary_currency TEXT,
                    description TEXT,
                    first_seen TEXT,
                    last_seen TEXT
                );
                INSERT INTO postings VALUES (
                    1, 'Data Analyst', 'Example Co', 'https://jobs.example/analyst',
                    'board', 'Remote', NULL, 40000, 50000, 'GBP', 'Analyse useful things.',
                    '2026-01-01T10:00:00+00:00', '2026-01-03T10:00:00+00:00'
                );
                """
            )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_imports_postings_and_preserves_source_dates(self) -> None:
        result = import_postings(self.database, self.store)
        listing = self.store.get_listing(self.store.list_listings()[0]["id"])
        self.assertIsNotNone(listing)

        self.assertEqual(result, {"imported": 1, "skipped": 0})
        assert listing is not None
        self.assertEqual(listing["title"], "Data Analyst")
        self.assertEqual(listing["salary"], "GBP 40,000–50,000")
        self.assertEqual(listing["source"], "board")
        self.assertEqual(listing["first_seen"], "2026-01-01T10:00:00+00:00")
        self.assertEqual(listing["snapshots"][0]["captured_at"], "2026-01-03T10:00:00+00:00")

    def test_import_is_repeatable_and_source_database_stays_readable(self) -> None:
        import_postings(self.database, self.store)
        result = import_postings(self.database, self.store)

        self.assertEqual(result, {"imported": 0, "skipped": 1})
        with closing(sqlite3.connect(self.database)) as connection:
            count = connection.execute("SELECT COUNT(*) FROM postings").fetchone()[0]
        self.assertEqual(count, 1)

    def test_rejects_database_without_postings_table(self) -> None:
        empty = self.root / "empty.sqlite3"
        with closing(sqlite3.connect(empty)):
            pass

        with self.assertRaisesRegex(ValueError, "no postings table"):
            import_postings(empty, self.store)

    def test_rejects_missing_database_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not exist"):
            import_postings(self.root / "missing.sqlite3", self.store)

    def test_invalid_posting_does_not_partially_import(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "INSERT INTO postings (title, company, description) VALUES (?, ?, ?)",
                ("Another role", "Another Co", "x" * 20_001),
            )
            connection.commit()

        with self.assertRaisesRegex(ValueError, "description must be at most"):
            import_postings(self.database, self.store)
        self.assertEqual(self.store.list_listings(), [])

    def test_command_line_import_uses_selected_replay_database(self) -> None:
        target = self.root / "from-cli.sqlite3"
        output = io.StringIO()
        arguments = [
            "job-replay",
            "--database",
            str(target),
            "--import-career-ops",
            str(self.database),
        ]

        with patch.object(sys, "argv", arguments), redirect_stdout(output):
            main()

        self.assertIn("1 snapshots added, 0 duplicates skipped", output.getvalue())
        imported = ReplayStore(target)
        self.assertEqual(len(imported.list_listings()), 1)


if __name__ == "__main__":
    unittest.main()
