# Validation, security and reliability audit

Date: 21 November 2026. Scope: the backend (FastAPI, PostgreSQL) in this repository, its tests, and its
Docker deployment files. The Flutter app's code was reviewed but could not be compiled here (no
Flutter SDK can be downloaded in this environment); see "Not verified".

## How it was tested

Besides reading the code, three new test files attack the running API against a real PostgreSQL 16
database, with row-level security on, as a reviewer would:

- `tests/test_adversarial.py` reads the API's own list of endpoints and, for every endpoint:
  - calls it with no token, a garbage token and Basic auth (all must refuse);
  - sends no body, wrong body types, and for every field one of 21 hostile values (empty, spaces,
    20,000 characters, -1, 0, 10^30, decimals, booleans, NUL characters, HTML and script tags, SQL
    fragments, emoji and Gujarati text, path traversal, impossible dates, NaN, injection objects),
    with valid and invalid ids in the path and hostile values in every query parameter;
  - checks that no response is a server error and that no error shows tracebacks, SQL or file paths.
- `tests/test_security.py`: password guessing, registration flooding, forged, unsigned, expired and
  tampered tokens, refresh-token replay, raising one's own role, reading and changing another
  company's records by id, stored script text, and oversized or malformed bodies.
- `tests/test_concurrency.py`: simultaneous LR bookings, the same save sent twice at once, and two
  collectors paid for the same balance at the same moment.

## What was found and fixed

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | High | Any text containing a NUL character crashed the request with a server error (PostgreSQL cannot store NUL). Found on 170+ endpoint/field combinations, including sign-in and password reset. | A request guard refuses NUL in JSON bodies, paths and query strings with a clear 422. |
| 2 | High | Unlimited password guessing on sign-in. | After 5 wrong passwords for one account, or 30 from one address, in 15 minutes, sign-in pauses for that account or address (429). Unknown accounts count the same, so the limit reveals nothing. Failures are recorded outside the failing request so a rollback cannot erase them. |
| 3 | High | PyJWT 2.7 had 17 published vulnerabilities (`pip-audit`). The project allowed versions back to 2.8. | Minimum raised to 2.15; all dependency versions pinned in `backend/constraints.txt` (scan now clean). |
| 4 | High | Deployment: if the API is reached over plain HTTP on port 8000, passwords and tokens cross the network readable. | Optional HTTPS for the DuckDNS name (Caddy, automatic certificates), off by default so nothing changes until you choose; steps in `docs/DEPLOY.md`. |
| 5 | Medium | A huge `offset` (e.g. 10^20) crashed list endpoints. | Every `offset` capped at 1,000,000. |
| 6 | Medium | Creating a branch with an existing name crashed (database duplicate error). Any future unchecked duplicate would do the same. | Branch names checked first (409). Database duplicate and out-of-range errors now answer 409 or 422 with a plain message, never 500. |
| 7 | Medium | Unexpected errors returned FastAPI's plain-text page, validation errors used a different shape from other errors, and 404s for unknown paths were plain text. | One JSON error shape everywhere: `{"error": {"code", "message", "fields"}}`, naming each bad field. Unexpected errors are logged with a reference number; the person sees only the reference. FastAPI's `detail` list is kept in 422s so older app builds still read them. |
| 8 | Medium | The interactive API docs and full schema were public in production. | Hidden when `FF_ENV=production` (the Compose default). |
| 9 | Medium | Password reset codes and full message text were written to the server log when no SMS or email provider is set. | In production the log records only that a message was not sent, with the number masked. |
| 10 | Medium | No security headers. | `nosniff`, `X-Frame-Options: DENY`, a restrictive Content-Security-Policy, no referrer, and HSTS when served over HTTPS. |
| 11 | Medium | Behind a reverse proxy every caller would share the proxy's address, so per-address limits would block everyone together. | uvicorn now trusts `X-Forwarded-For` only from the configured proxy (`FF_FORWARDED_ALLOW_IPS`). |
| 12 | Medium | One address could register unlimited companies. | 5 registrations per address per hour. |
| 13 | Medium | Request bodies had no size limit. | JSON over 1 MB and uploads over 25 MB refused with 413 before being read. |
| 14 | Medium | The test suite drops the whole schema of the database it is pointed at; a mistyped variable could wipe a real database. | Tests refuse to run unless both database names end in `_test`. |
| 15 | Low | The API could start in production with the example JWT secret from `.env.example`. | Refuses to start in production with it. |
| 16 | Low | Containers did not restart after a crash or a server reboot. | `restart: unless-stopped` on the database and API. |

## Verified to be already correct (tests added to keep it so)

- **Another company's records:** reading, cancelling, hiring, voiding, editing or receipting them by id answers "not found"; lists show nothing of them. The database's row-level security enforces this, not only the code.
- **Branch staff:** they see only their branch, including through the database directly.
- **Forged, unsigned (`alg: none`), expired and tampered tokens** are refused. Reusing a refresh token signs out every session.
- **Raising one's own role:** a clerk cannot change their role or permissions through `/me`, `/users`, or invites.
- **Script and SQL text:** stored as text, and escaped on the one HTML page (the receipt check). Every query uses bound parameters.
- **Simultaneous bookings:** they get distinct, gap-free numbers.
- **The same save sent twice:** with a request key, it books one LR.
- **Two collectors and one balance:** cannot both be paid for it.
- **Money and finalised records:**
  - Payments, receipts, owner payments, handovers, deposits and the audit log are insert-only for the API's database role.
  - Sealed challans and saved LRs cannot be edited.
  - Corrections go through reversals or cancellations with reasons.
- **No secrets in the repository:** no keys, passwords or `.env` files are in the source or the ZIP.

## Not verified here, and remaining risks

- **The Flutter app was not compiled or run.** No Flutter SDK can be downloaded in this environment. Its code passed static checks for brackets, imports and unused code only. Run `flutter pub get`, `flutter analyze` and `flutter test` before the review.
- **The Docker image was not built here.** Docker isn't available in this environment. The same dependency set was installed into a clean Python environment from the pins and the full suite passed there.
- **I have not seen the EC2 server.** Its proxy, firewall, process manager and current code version are unknown to me. `docs/DEPLOY.md` says what to check before applying anything, and requires a backup because migrations run on start.
- **Migrations run when the API container starts, using the database owner's password.** This was kept to preserve the current deployment. A cleaner setup runs migrations as a separate step and gives the API only the restricted role.
- **Rate limits live in the database.** They are fine for one server; they are not a defence against a large distributed attack.
- **Uploaded photos and statements are checked by type and size, not scanned for malware.** They are never executed or served back as HTML.
- **No external penetration test was done.** "No issues found by these tests" is not the same as "secure".
