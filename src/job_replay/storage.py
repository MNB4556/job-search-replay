"""SQLite storage for listings and their successive snapshots."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

FIELDS = ("title", "company", "url", "source", "location", "salary", "description")
REQUIRED_FIELDS = ("title", "company")
FIELD_LIMITS = {
    "title": 500,
    "company": 500,
    "url": 2_000,
    "source": 200,
    "location": 500,
    "salary": 500,
    "description": 20_000,
}
SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY,
    identity_key TEXT NOT NULL UNIQUE,
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    captured_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS snapshots_listing_id_id
    ON snapshots(listing_id, id);
"""


def _timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _normalise_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValueError("url must be an http or https address")
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, "")
    )


def _clean_payload(data: object) -> dict[str, str]:
    if not isinstance(data, dict):
        raise ValueError("request body must be a JSON object")

    payload: dict[str, str] = {}
    for field in FIELDS:
        value = data.get(field, "")
        if not isinstance(value, str):
            raise ValueError(f"{field} must be text")
        value = value.strip()
        if len(value) > FIELD_LIMITS[field]:
            raise ValueError(f"{field} must be at most {FIELD_LIMITS[field]} characters")
        payload[field] = value

    for field in REQUIRED_FIELDS:
        if not payload[field]:
            raise ValueError(f"{field} is required")
    if payload["url"]:
        payload["url"] = _normalise_url(payload["url"])
    return payload


class ReplayStore:
    """Persist listing identity and each distinct captured version."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def record_snapshot(self, data: object) -> tuple[dict[str, object], bool]:
        payload = _clean_payload(data)
        if payload["url"]:
            identity_key = f"url:{payload['url']}"
        else:
            company = re.sub(r"\s+", " ", payload["company"]).casefold()
            title = re.sub(r"\s+", " ", payload["title"]).casefold()
            identity_key = f"job:{company}|{title}"

        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        now = _timestamp()
        with closing(self._connect()) as connection:
            with connection:
                row = connection.execute(
                    "SELECT id FROM listings WHERE identity_key = ?", (identity_key,)
                ).fetchone()
                if row is None:
                    cursor = connection.execute(
                        "INSERT INTO listings (identity_key, first_seen) VALUES (?, ?)",
                        (identity_key, now),
                    )
                    listing_id = cursor.lastrowid
                    changed = True
                else:
                    listing_id = row["id"]
                    latest = connection.execute(
                        "SELECT payload FROM snapshots WHERE listing_id = ? ORDER BY id DESC LIMIT 1",
                        (listing_id,),
                    ).fetchone()
                    changed = latest is None or latest["payload"] != encoded

                if changed:
                    connection.execute(
                        "INSERT INTO snapshots (listing_id, captured_at, payload) VALUES (?, ?, ?)",
                        (listing_id, now, encoded),
                    )

        listing = self.get_listing(listing_id)
        if listing is None:
            raise RuntimeError("saved listing could not be read back")
        return listing, changed

    def list_listings(self) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT l.id, l.first_seen, latest.captured_at AS last_seen,
                       latest.payload, counts.snapshot_count
                FROM listings AS l
                JOIN snapshots AS latest
                  ON latest.id = (
                      SELECT MAX(s.id) FROM snapshots AS s WHERE s.listing_id = l.id
                  )
                JOIN (
                    SELECT listing_id, COUNT(*) AS snapshot_count
                    FROM snapshots GROUP BY listing_id
                ) AS counts ON counts.listing_id = l.id
                ORDER BY latest.captured_at DESC, l.id DESC
                """
            ).fetchall()
        return [self._listing_from_row(row) for row in rows]

    def get_listing(self, listing_id: int) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            listing = connection.execute(
                "SELECT id, first_seen FROM listings WHERE id = ?", (listing_id,)
            ).fetchone()
            if listing is None:
                return None
            snapshots = connection.execute(
                "SELECT id, captured_at, payload FROM snapshots "
                "WHERE listing_id = ? ORDER BY id ASC",
                (listing_id,),
            ).fetchall()

        history = [
            {
                "id": row["id"],
                "captured_at": row["captured_at"],
                **json.loads(row["payload"]),
            }
            for row in snapshots
        ]
        latest = history[-1]
        return {
            "id": listing["id"],
            "first_seen": listing["first_seen"],
            "last_seen": latest["captured_at"],
            "snapshot_count": len(history),
            **{field: latest[field] for field in FIELDS},
            "snapshots": history,
        }

    @staticmethod
    def _listing_from_row(row: sqlite3.Row) -> dict[str, object]:
        return {
            "id": row["id"],
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "snapshot_count": row["snapshot_count"],
            **json.loads(row["payload"]),
        }
