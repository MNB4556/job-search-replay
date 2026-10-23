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


def _identity_key(payload: dict[str, str]) -> str:
    if payload["url"]:
        return f"url:{payload['url']}"
    company = re.sub(r"\s+", " ", payload["company"]).casefold()
    title = re.sub(r"\s+", " ", payload["title"]).casefold()
    return f"job:{company}|{title}"


def _clean_timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("captured_at must be an ISO-8601 timestamp")
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("captured_at must be an ISO-8601 timestamp") from error
    if timestamp.tzinfo is None:
        raise ValueError("captured_at must include a timezone")
    return timestamp.astimezone(UTC).replace(microsecond=0).isoformat()


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

    def record_snapshot(
        self,
        data: object,
        captured_at: str | None = None,
        first_seen: str | None = None,
    ) -> tuple[dict[str, object], bool]:
        payload = _clean_payload(data)
        captured_at = _clean_timestamp(captured_at) if captured_at else _timestamp()
        first_seen = _clean_timestamp(first_seen) if first_seen else captured_at
        with closing(self._connect()) as connection, connection:
            listing_id, changed = self._record_snapshot(
                connection, payload, captured_at, first_seen
            )
        listing = self.get_listing(listing_id)
        if listing is None:
            raise RuntimeError("saved listing could not be read back")
        return listing, changed

    def export_data(self) -> dict[str, object]:
        return {
            "format": "job-search-replay",
            "version": 1,
            "exported_at": _timestamp(),
            "listings": self.list_listings_with_history(),
        }

    def import_data(self, data: object) -> dict[str, int]:
        if not isinstance(data, dict) or data.get("format") != "job-search-replay":
            raise ValueError("file is not a Job Search Replay backup")
        version = data.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version != 1:
            raise ValueError("unsupported backup version")
        listings = data.get("listings")
        if not isinstance(listings, list):
            raise ValueError("backup listings must be a list")

        validated: list[tuple[dict[str, str], str, str | None]] = []
        for listing in listings:
            if not isinstance(listing, dict) or not isinstance(listing.get("snapshots"), list):
                raise ValueError("each backup listing must contain a snapshots list")
            first_seen = listing.get("first_seen")
            if first_seen is not None:
                first_seen = _clean_timestamp(first_seen)
            if not listing["snapshots"]:
                raise ValueError("backup listings must contain at least one snapshot")
            for snapshot in listing["snapshots"]:
                if not isinstance(snapshot, dict):
                    raise ValueError("each snapshot must be an object")
                validated.append(
                    (
                        _clean_payload(snapshot),
                        _clean_timestamp(snapshot.get("captured_at")),
                        first_seen,
                    )
                )

        imported = 0
        skipped = 0
        with closing(self._connect()) as connection, connection:
            for payload, captured_at, first_seen in validated:
                _, changed = self._record_snapshot(
                    connection, payload, captured_at, first_seen, importing=True
                )
                if changed:
                    imported += 1
                else:
                    skipped += 1
        return {"imported": imported, "skipped": skipped}

    def list_listings_with_history(self) -> list[dict[str, object]]:
        return [
            self.get_listing(listing["id"])
            for listing in self.list_listings()
        ]

    def delete_listing(self, listing_id: int) -> bool:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
        return cursor.rowcount > 0

    @staticmethod
    def _record_snapshot(
        connection: sqlite3.Connection,
        payload: dict[str, str],
        captured_at: str,
        first_seen: str | None = None,
        importing: bool = False,
    ) -> tuple[int, bool]:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        row = connection.execute(
            "SELECT id FROM listings WHERE identity_key = ?", (_identity_key(payload),)
        ).fetchone()
        if row is None:
            cursor = connection.execute(
                "INSERT INTO listings (identity_key, first_seen) VALUES (?, ?)",
                (_identity_key(payload), first_seen or captured_at),
            )
            listing_id = cursor.lastrowid
            changed = True
        else:
            listing_id = row["id"]
            if importing and first_seen is not None:
                connection.execute(
                    "UPDATE listings SET first_seen = ? "
                    "WHERE id = ? AND first_seen > ?",
                    (first_seen, listing_id, first_seen),
                )
            if importing:
                duplicate = connection.execute(
                    "SELECT 1 FROM snapshots "
                    "WHERE listing_id = ? AND captured_at = ? AND payload = ? LIMIT 1",
                    (listing_id, captured_at, encoded),
                ).fetchone()
                changed = duplicate is None
            else:
                latest = connection.execute(
                    "SELECT payload FROM snapshots WHERE listing_id = ? "
                    "ORDER BY captured_at DESC, id DESC LIMIT 1",
                    (listing_id,),
                ).fetchone()
                changed = latest is None or latest["payload"] != encoded

        if changed:
            connection.execute(
                "INSERT INTO snapshots (listing_id, captured_at, payload) VALUES (?, ?, ?)",
                (listing_id, captured_at, encoded),
            )
        return listing_id, changed

    def list_listings(self) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT l.id, l.first_seen, latest.captured_at AS last_seen,
                       latest.payload, counts.snapshot_count
                FROM listings AS l
                JOIN snapshots AS latest
                  ON latest.id = (
                      SELECT s.id FROM snapshots AS s WHERE s.listing_id = l.id
                      ORDER BY s.captured_at DESC, s.id DESC LIMIT 1
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
                "WHERE listing_id = ? ORDER BY captured_at ASC, id ASC",
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
