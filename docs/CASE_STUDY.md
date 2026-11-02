# Replay: the history of a job advert

## The problem

Job adverts are edited, reposted and removed, but job-search tools treat them as
stable records. Save only the link and the original wording is gone when you want
to revisit it. Existing tools cover discovery, or application tracking. Replay
covers the part between those two: what the advert said, and how it changed.

## The product decision

Replay is manual and local. You decide which details to keep, then capture the
same listing again when you want to compare. The interface answers one question:
what changed since I last saw this role?

That scope avoids writing another job-board scraper and avoids collecting career
data in a hosted service. A capture is a dated record. It is not a claim that the
advert is still live, or that the employer is trustworthy.

## The central interaction

1. Save a title and company, plus any URL, salary, location, source or advert
   text worth keeping.
2. Return to the listing and choose Recapture to start from the latest version.
3. Edit the details and save. An unchanged capture is ignored; a distinct version
   is added to the history.
4. Read the timeline to see which fields changed, and when.

The demo backup contains fictional listings, so the history can be explored
without entering personal data.

## How it is built

- Python 3.11+ standard library serves the local web app and JSON API.
- SQLite stores listing identity and immutable captured versions.
- Plain HTML, CSS and JavaScript render the interface. There is no frontend build
  step and no runtime package.
- Listing identity uses the normalised advert URL when available, otherwise
  normalised company and title. Identical repeated snapshots are dropped.
- Backup imports are validated before writing and applied in a transaction.
  Re-importing a backup skips snapshots with the same identity, timestamp and
  contents.
- The optional career-ops importer opens the source SQLite file read-only and
  imports discovered adverts, not application statuses or private notes.

## Privacy boundary

The app binds to `127.0.0.1` and has no user authentication. It is a local
prototype, not a multi-user service. The data file and exported backups may
contain personal information and should stay private. Do not expose the server to
a network or the internet.

The server checks the request Host header and sets restrictive browser headers,
but neither makes the app production-ready. There is no account system,
authorisation model, TLS, deployment architecture or security review.

## What is not built

- No automatic scraping or background polling.
- No accounts, cloud sync, analytics or hosted database.
- No application-status tracker; career-ops remains the source for that.
- No guarantee that an edit to an advert reflects the employer's intent.
- No sentence-level description diff; text changes are shown as before and after
  values.

## Validation

The tests cover storage identity and deduplication, transactional import and
rollback, demo data, the read-only career-ops bridge, HTTP behaviour and localhost
request filtering. GitHub Actions runs them with lint checks on Python 3.11 to
3.14, plus a JavaScript syntax check.

## Hosting would be a different project

A hosted version needs accounts and authorisation, tenant isolation,
data-retention and deletion policies, privacy and legal review, threat modelling,
hardened hosting, monitoring, backup and restore operations, and a wider security
and accessibility review. The current local server should not be exposed to the
internet as it stands.

## Next

1. Import saved application records from career-ops without duplicating its
   tracker.
2. Improve long-description comparison while preserving the original text.
3. Validate a browser-assisted capture flow with an explicit preview and a save
   the user controls.
4. Get feedback before deciding whether a hosted version is worth building.
