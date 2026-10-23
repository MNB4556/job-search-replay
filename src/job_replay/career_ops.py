"""Read-only import of discovered postings from a career-ops SQLite database."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from job_replay.storage import ReplayStore

REQUIRED_COLUMNS = {"title", "company"}
OPTIONAL_COLUMNS = {
    "url",
    "source",
    "location",
    "salary",
    "salary_min",
    "salary_max",
    "salary_currency",
    "description",
    "first_seen",
    "last_seen",
}


def import_postings(database_path: str | Path, store: ReplayStore) -> dict[str, int]:
    """Import career-ops discovered postings, opening its database read-only."""
    source_path = Path(database_path).expanduser().resolve()
    if not source_path.is_file():
        raise ValueError(f"career-ops database does not exist: {source_path}")

    uri = f"{source_path.as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'postings'"
            ).fetchone()
            if table is None:
                raise ValueError("career-ops database has no postings table")
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(postings)")
            }
            missing = REQUIRED_COLUMNS - columns
            if missing:
                raise ValueError(
                    "career-ops postings table is missing required columns: "
                    + ", ".join(sorted(missing))
                )
            selected = sorted(columns & OPTIONAL_COLUMNS | REQUIRED_COLUMNS)
            rows = connection.execute(
                f"SELECT {', '.join(selected)} FROM postings ORDER BY id"
            ).fetchall()
    except sqlite3.DatabaseError as error:
        raise ValueError(f"could not read a career-ops SQLite database: {error}") from error

    backup_listings: list[dict[str, object]] = []
    for row in rows:
        values = dict(row)
        salary = values.get("salary") or _format_salary(values)
        payload = {
            "title": values["title"],
            "company": values["company"],
            "url": values.get("url") or "",
            "source": values.get("source") or "",
            "location": values.get("location") or "",
            "salary": salary,
            "description": values.get("description") or "",
        }
        backup_listings.append(
            {
                "first_seen": values.get("first_seen"),
                "snapshots": [
                    {
                        "captured_at": values.get("last_seen"),
                        **payload,
                    }
                ],
            }
        )
    return store.import_data(
        {"format": "job-search-replay", "version": 1, "listings": backup_listings}
    )


def _format_salary(posting: dict[str, object]) -> str:
    minimum = posting.get("salary_min")
    maximum = posting.get("salary_max")
    currency = posting.get("salary_currency")
    if minimum is None and maximum is None:
        return ""
    if minimum is not None and maximum is not None:
        amount = f"{minimum:,}–{maximum:,}"
    else:
        amount = f"{minimum if minimum is not None else maximum:,}"
    return f"{currency} {amount}".strip()
