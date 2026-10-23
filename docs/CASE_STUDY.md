# Replay: keep the story behind a job listing

## The problem

Job adverts are treated like stable records, but they are edited, reposted, and
removed. If a candidate saves only the link, the original wording and terms may
be gone when they want to revisit the opportunity. Job-search tools often focus
on discovery or application tracking; Replay focuses on the missing history
between those moments.

## The product decision

Replay is deliberately a **manual, local-first prototype**. A person decides
which listing details to keep, then captures the same listing again when they
want to compare it. The interface answers one question clearly: *what changed
since I last saw this role?*

This scope avoids building another job-board scraper and avoids collecting
career data in a hosted service. A capture is a dated record, not a claim that
an advert is still live or that its employer is trustworthy.

## The central interaction

1. Save a title and company, plus any URL, salary, location, source, or advert
   text worth remembering.
2. Return to the listing and choose **Recapture** to start from the latest
   version.
3. Edit the current details and save. An unchanged capture is ignored; a
   distinct version is added to the history.
4. Read the timeline to see which fields changed and when.

The demo backup contains fictional listings so the history can be explored
without entering personal data.

## How it is built

- **Python 3.11+ standard library** serves the local web app and JSON API.
- **SQLite** stores listing identity and immutable captured versions.
- **Plain HTML, CSS, and JavaScript** render the interface; there is no
  frontend build step or runtime package.
- Listing identity uses the normalized advert URL when available, otherwise
  normalized company and title. Exact repeated snapshots are deduplicated.
- Backup imports are validated before writes and applied in a SQLite
  transaction. Re-importing a backup skips snapshots with the same identity,
  timestamp, and contents.
- The optional career-ops importer opens the source SQLite file read-only and
  imports discovered adverts—not application statuses or private notes.

## Privacy boundary

The app binds to `127.0.0.1` by default and has no user authentication. It is a
personal-use local prototype, not a multi-user service. The data file and
exported backups may contain personal information and should remain private.
Do not expose the server to a network or the public internet.

The server checks the request Host header and sets restrictive browser headers,
but those safeguards do **not** make this app production-ready. There is no
account system, authorization model, TLS, deployment architecture, or formal
security review.

## What is intentionally not built

- No automatic scraping or background polling.
- No accounts, cloud sync, analytics, or hosted database.
- No application-status tracker; career-ops remains the source for that.
- No guarantee that edits to an advert represent the employer's intent.
- No semantic, sentence-level description diff yet; text changes are shown as
  before/after values.

These are explicit boundaries for the prototype, not hidden capabilities.

## Validation

The project tests storage identity and deduplication, transactional import and
rollback, demo data, the read-only career-ops bridge, HTTP behavior, and
localhost request filtering. The GitHub Actions workflow runs the tests and
lint checks on Python 3.11–3.14, plus a JavaScript syntax check.

## Production is a different project phase

Before offering Replay as a hosted service, it would need a new architecture:
user accounts and authorization, secure tenant isolation, data-retention and
deletion policies, privacy/legal review, threat modeling, hardened hosting,
monitoring, backup/restore operations, and a broader security and accessibility
review. The current local server should not simply be exposed to the internet.

## Next experiments

1. Import saved application records from career-ops without duplicating its
   existing tracker.
2. Improve long-description comparison while preserving the original text.
3. Validate a browser-assisted capture flow with an explicit preview and
   user-controlled save.
4. Gather feedback before deciding whether a hosted version is worth building.
