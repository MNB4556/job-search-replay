# Job Search Replay

A local-first tool for keeping snapshots of job adverts and seeing how they
change over time.

## First slice

- Add or recapture a listing from the local web page.
- Keep each distinct version in a SQLite database on this machine.
- Browse a listing's snapshot history and see which fields changed.
- Use no accounts, scraping, or third-party services.

Career-ops import and automatic discovery are intentionally out of scope for
this first slice.

## Requirements

- Python 3.11+

## Run

From this directory in PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m job_replay
```

Then open <http://127.0.0.1:8000>. Press Ctrl+C in the terminal to stop the
server. The database is created at `data/replay.sqlite3`; set
`JOB_REPLAY_DB` to use a different path.

Only bind this development app to localhost. It has no authentication.

For a different shell, set `PYTHONPATH` to `src` before running the command.

## API

- `GET /api/listings` — list tracked listings
- `GET /api/listings/{id}` — listing details and snapshots
- `POST /api/snapshots` — create a listing or capture a changed version

The POST endpoint accepts JSON fields `title` and `company` (required), plus
`url`, `source`, `location`, `salary`, and `description`. A listing is matched
by URL when present, otherwise by company and title. Identical captures are
ignored.

## Development

Run the tests with:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
```
