# FreightFlow AI

Accounts, master data, LRs with invoice scan and printing, pending goods, load planning, trips, delivery, chat and dashboard.

- `backend/`: FastAPI and PostgreSQL. Tested.
- `app/`: Flutter app for the same slice. Not compiled; see `app/README.md`.

The rest of this file covers the backend.

## What is in this slice

| Area | Endpoints |
| --- | --- |
| Auth | `POST /auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/invites/accept` |
| Account recovery | `POST /auth/password/forgot` (emails a 6-digit code), `POST /auth/password/reset`, `POST /auth/email/recover` (texts the login email to the account's phone). Replies never reveal whether an account exists. |
| Profile | `GET /me`, `PATCH /me`, `POST /me/password` |
| Users (admin) | `GET /users`, `POST /users/invites`, `PATCH /users/{id}`, `POST /users/{id}/password` |
| Company | `GET /company`, `PATCH /company` (admin) |
| Master data | `/parties`, `/item-types`, `/trucks`: list, get, create, update. Admin and manager write; everyone reads. |
| LRs | `POST /lrs` saves with the next number; `GET /lrs`, `GET /lrs/{id}`, `GET /lrs/{id}/pdf?copy=all|consignee|office|driver1|driver2` (four labelled copies, or one); `GET /lrs/register.pdf?date_from=&date_to=`; `GET /lrs/parties?q=&role=` (autocomplete); `POST /lrs/{id}/cancel` (admin, manager). A saved LR is never edited. |
| LR form helpers | `GET /lrs/defaults` (provisional number, from city, ST. charges), `GET /lrs/suggestions` (the consignor's last LR), `POST /lrs/print-preview` (PDF, nothing saved) |
| LR settings | `GET /lrs/settings`, `PATCH /lrs/settings` (admin): number prefix and next number, from city, default ST. charges |
| E-way bill | `GET /eway/states` (state codes and intra-state limits), `POST /eway/evaluate` (is a bill needed, why, who generates it, Part B, validity), `PATCH /lrs/{id}/eway-bill` (add the number after booking) |
| Rate matrix | `/stations`, `/routes`, `/rate-rules` (list, get, create, update), `GET /rates/classes`, `POST /rates/quote` (freight with the working shown) |
| Payments | `GET /lrs/{id}/account` (what an LR owes and every collection set against it), `GET /receivables`, `GET /receivables/lrs?party=` |
| Collections | `POST /receipts` (money receipt for one payer's LRs; amount from the LRs), `GET /receipts`, `GET /receipts/{id}`, `GET /receipts/{id}/pdf`, `POST /receipts/{id}/cancel`, `POST /receipts/{id}/visits` (paid, part paid, come later, refused), `POST /collections/{id}/fail`, `GET /custody`, `GET /custody/me`, `POST /handovers`, `POST /handovers/{id}/confirm`, `POST /deposits`, `GET/PUT /credit-terms`, `POST /lrs/{id}/release-approval`, `POST /lrs/{id}/gate-pass`, `GET /shortages`, `POST /shortages/{id}/decide`, `GET /collections/overview`, `GET /collections/daily-summary`; public `GET /r/{token}` (the receipt check page its QR opens) |
| Bank | `POST /bank/statements/preview`, `POST /bank/statements` (CSV, XLS or XLSX; layout found by column names and remembered), `GET /bank/lines`, `POST /bank/lines/{id}/match`, `/allocate`, `/ignore` |
| Branches | `GET /branches`, `POST /branches`, `PUT /branches/{id}` (cities each branch delivers) |
| Delivery | `POST /gate-passes` (one consignee, several LRs), `GET /gate-passes`, `GET /gate-passes/{id}`, `/pdf`, `/photo`, `POST /gate-passes/{id}/delivery` (proof: signature, time, place, photo; multipart), `POST /gate-passes/{id}/void` |
| Approvals | `POST /lrs/{id}/release-request`, `GET /approvals`, `POST /approvals/{id}/decide` |
| Tasks | `GET /tasks?scope=mine|all`, `POST /tasks/{id}/attempts`, `POST /tasks/{id}/assign` |
| Reminders | `POST /reminders/run`, `GET /reminders?payer=` |
| Operations | `GET /dashboard/operations` (whole business for the owner; one branch for a branch manager) |
| Analytics | `GET /analytics/{overview,trend,customers,lanes,rates,execution,fleet,finance,branches,insights}` with `period` or `date_from`/`date_to`, `customer`, `customer_role`, `origin`, `destination`, `freight_by`, `stage`, `branch_id`; `GET /analytics/{name}/export?format=xlsx|pdf`; `POST /analytics/custom` and `/custom/export`; `GET /analytics/options`; saved and scheduled reports at `/analytics/saved` |
| Truck hire | `GET/POST/PUT /vendors`; `GET /trips/{id}/money`, `PUT /trips/{id}/hire`, `POST /trips/{id}/owner-payments` (advance, balance, reversal), `/deductions`, `/expenses`; `GET /payables` |
| Quotes | `POST /rfqs`, `GET /rfqs`, `GET /rfqs/{id}`, `POST /rfqs/{id}/quotes`, `/remind`, `/award`, `/cancel` |
| Contracts | `GET/POST/PUT /contracts`, `GET /contracts/rate?party=&destination=`; `GET/PUT /transit-times` |
| Invoice scan | `POST /invoices/scan` (photo upload): reads consignor, consignee, GST numbers, city, goods, value and e-way bill number. Nothing is saved and the photo is not kept. |
| Pending | `GET /pending` (by destination), `GET /pending/lrs?destination=&older_than_days=` (oldest first) |
| Trips | `GET /trips/suggestions` (which truck for which route), `POST /trips/plan` (load for a truck and its stops), `POST /trips` (dispatch to one or more stops, partial loads allowed), `POST /trips/{id}/stops/{city}/deliver` (unload a whole stop), `GET /trips`, `GET /trips/{id}`, `POST /trips/{id}/lines/{line_id}/deliver`, `POST /trips/{id}/lines/{line_id}/undo-delivery` (admin, manager), `GET /trips/{id}/load-sheet.pdf` |
| Chat | `POST /chat`: answers from nine read-only tools (LR details, pending, bookings by day, trucks, party search); understands typos, everyday words and follow-up questions; refuses anything that would change data; every question is audited |
| Cargo added on the road | `POST /trips/{id}/additions` (request), `GET /trips/{id}/challans`, `GET /challans/open`, `POST /challans/{id}/approve`, `/void`, `/sign` (driver sign-off, which issues and seals the challan) |
| Dashboard | `GET /dashboard`, `GET /dashboard/admin` (owner: trucks, trips, freight, receivables, expiring e-way bills) |
| Ops | `GET /health` |

Interactive API docs are at `/docs` once the server is running.

## Run it

```
cp .env.example .env      # then replace every value
docker compose up --build
```

The API listens on port 8000. Migrations run on start, so on a server with data, back up first:
see `docs/DEPLOY.md`. Optional HTTPS for a DuckDNS name: `docker compose --profile https up -d`.

The Flutter app (`app/`): `flutter pub get`, then `flutter run --dart-define=API_BASE_URL=https://your-name.duckdns.org`.

## Run the tests

The tests need a real PostgreSQL 16, because they check row-level security and table privileges.

```
psql -U postgres -c "CREATE ROLE freightflow_owner LOGIN PASSWORD 'owner' CREATEDB"
psql -U postgres -c "CREATE ROLE freightflow_app LOGIN PASSWORD 'app'"
psql -U postgres -c "CREATE DATABASE freightflow_test OWNER freightflow_owner"
cd backend
pip install -c constraints.txt -e ".[dev]"
pytest -q          # about 5 minutes; refuses any database not named *_test
```

The tests also need **Tesseract** installed (`apt install tesseract-ocr`, or the Windows installer
with `tesseract` on the PATH), because the scan tests read a generated image. Docker installs it for
the running backend.

## Rules the code relies on

- **One transaction per request.** `get_session` commits on success and rolls back on any exception.
- **Tenant scope.** `current_user` calls `set_tenant`, and every table has a row-level security policy on `company_id`. A query that forgets its company filter still returns only the caller's rows.
- **Two database roles.** Migrations run as `freightflow_owner`. The API runs as `freightflow_app`, which has no DELETE on any table and no UPDATE on `audit_log`.
- **Deactivate, never delete.** There are no DELETE endpoints. Use `PATCH` with `is_active: false`.
- **Module shape.** Each module is `schemas.py`, `service.py`, `router.py`. Routers hold no logic. Modules call each other only through `service`.
- **Nothing is half-saved.** An LR is saved when it is printed and a trip when it is dispatched; both are
  drafts on the phone until then. Saved LRs and trips are never edited.
- **Pending is calculated, not stored.** It is always an LR's packages minus what trips have taken, and
  dispatch locks the LR rows while it checks, so the same packages cannot be loaded twice.
- **The load planner is a pure function** in `app/planner/planner.py`. Version 1 checks space and weight
  with 85% of the truck body counted as usable; it does not place boxes in 3D.
- **Chat** picks a tool with word and pattern rules in `app/chat/interpreter.py` (English, with some Hindi words such as baki, aaj, kal). A language model
  can replace that one function without touching the tools, permissions or audit log.
- **The LR header is the company's own.** Name, tagline, address (up to 3 lines), GSTIN and contact number
  come from Company settings, so another transporter prints its own header on the same form.
- **Recovery never confirms an account.** Forgot-password and find-my-email give the same reply for any
  input, send their message after the reply, and allow 3 requests an hour per account and 10 per IP. A
  reset code is 6 digits, stored as a keyed hash, single use, valid 15 minutes, and dies after 5 wrong tries.
- **SMS is not connected.** `Outbox.sms` in `app/notify.py` only logs. Find-my-email needs a provider
  wired in there before it can reach a phone.
- **Reports** use `build_table_report` in `app/reports/pdf.py`: give it columns and rows and it handles
  page breaks, the repeated heading row and "Page x of y".
- **E-way bill rules are one pure module**, `app/eway/rules.py`, decided again by the server when an LR
  is saved. State limits live in `app/eway/states.py` with the date they were last reviewed; update that
  file when a state changes its notification. The app records and enforces; it does not file anything
  with the e-way bill portal.
- **An LR that needs a bill cannot be dispatched without its number.** Dispatch is Part B: it records the
  vehicle and starts the validity clock (one day per 200 km). A truck whose insurance or fitness has
  expired cannot be dispatched either.
- **Freight comes from the rate matrix**, priced by the pure functions in `app/rates/engine.py`.
  Chargeable weight is packages x weight per package unless a total is given. A station belongs to a
  zone (its base station) and adds its own surcharge per kg; a rate is set per class of goods per zone,
  charged per kg, per package by weight slab, or per package flat.
- **A trip has ordered stops.** Each LR must be for one of them. Delivering a stop leaves the trip open
  while later stops have goods; the truck is free, and its location becomes the last stop, only when
  everything is delivered.
- **Truck suggestions** group pending LRs by saved route, give the longest-waiting group first pick, and
  choose the smallest free truck that takes everything. It is a rule-based planner, not a trained model.
- **Payments are insert-only**, cannot exceed the balance, and block cancelling the LR. Paid is due at
  booking, to-pay at delivery, to-be-billed 30 days after booking (`BILLING_CREDIT_DAYS`).
- **An issued challan is never edited.** Dispatch creates the trip's primary challan (CH-12). Cargo added
  on the road is a supplementary challan on the same trip (CH-12/S1): requested by whoever is loading,
  approved by the person who dispatched the trip (an admin, if that person asked for it), and issued
  when the driver signs for what was counted on. Lines are written only at sign-off. The database role
  the API runs as cannot change a challan's trip, number or requested lines, or a line's packages, and
  each issued challan carries a hash chained to the one before it, so direct tampering shows as
  `sealed: false`. Every request is re-checked at approval and at sign-off: stop order, pending
  packages, e-way bills, and weight and space on every remaining leg.
- **Money is collected so no one person controls it.** What is due comes from the sealed LR; a money
  receipt is issued by the app with that amount; the collector records each visit; the customer is
  messaged (SMS and WhatsApp, once a provider is plugged into `Outbox`); cash is counted at handover by a
  second person and banked in a numbered deposit; the bank statement confirms UPI by UTR, cheques by
  number and deposits by batch number or unambiguous amount. Collections, handovers and deposits are
  insert-only for the API's database role; balances are always worked out from them (`collections/balances.py`).
  A collector may take up to `collector_cash_limit` (Rs 25,000) in cash per receipt; nobody may take
  Rs 2 lakh or more in cash from one customer in a day.
- **Freight is never typed.** Each LR records its charge basis: per kg (rate x chargeable weight), per
  article (rate x packages) or the rate matrix, which the server prices again. LRs saved before the basis
  existed keep their freight (`charge_basis` null). The LR prints in three copies: yellow, white, pink.
- **Customer payment terms** (`credit_terms`): advance, before delivery, at delivery (the default for anyone
  without terms) or credit with a limit and days. Due dates follow the terms (`collections/credit.py`).
  From `lr_settings.credit_controls_from`, a payer over their limit or overdue by more than
  `overdue_hold_days` cannot be booked except by an admin with a reason. Reports: `/receivables/ageing`,
  `/receivables/priorities`.
- **Idempotency keys.** Booking, receipts, visits, handovers, deposits, dispatch and bank allocations accept
  an `Idempotency-Key` header; a retry with the same key returns the first answer (`app/idempotency.py`).
- **Branches are enforced by the database.** Every request sets `app.branches` ('all' for the owner and
  people with no branch, else the user's branch). Restrictive row-level policies on LRs, trips, receipts,
  collections, handovers, deposits, shortages, gate passes, tasks and approvals AND this with the company
  policy. An LR belongs to its booking branch and to the branch that delivers its destination city.
- **Permissions, not roles, guard every endpoint** (`app/permissions.py`). A role gives defaults; the
  owner grants or revokes single permissions per person. Owner-level permissions (`SENSITIVE`) can only be
  given by an owner. The app reads `/me.permissions` to decide what to offer; the server checks again.
- **Proof of delivery is the signed gate pass.** Due dates count from the consignee's signature. Only
  `delivery.correct` can undo it, with a reason; the proof stays on record. Proofs taken offline carry
  the phone's signing time and an idempotency key, so a late or repeated send is recorded once.
- **The daily job** creates and closes collection tasks and sends reminders for every company:
  `docker compose run --rm api python -m app.jobs daily`, from cron each morning. Opening a task list or
  the operations dashboard also refreshes tasks, so they are right even before the job runs.
- **Analytics read facts, not copies.** `app/analytics/facts.py` builds one row per LR from the LR, its
  trips, its gate pass and its collections; every analysis is computed from those rows, and every answer
  carries a `basis` saying how. Row-level security applies, so a branch manager's analytics, exports and
  scheduled reports hold their branch only. Scheduled reports are emailed as Excel by the daily job.
- **Every truck is hired.** The company owns none; the driver pays diesel, tolls and wages out of the hire.
  A trip's profit is the freight it carries (each LR's total shared by packages on the trip) minus the hire,
  plus deductions taken from the owner, minus office expenses. Owner payments are insert-only; the balance
  is paid after delivery (earlier only with `approvals.decide`); mistakes are reversed with a reason.
- **Contracts and transit times.** A customer's contract gives an agreed rate per destination for a period;
  the LR form starts from it and Analytics lists LRs charged differently. Usual transit times ("Raipur 4 to
  5 days") are what the office tells customers, not a promise; trips longer than the upper figure are late.
- **Adding a tenant table.** Add it to `TENANT_TABLES` in a new migration so it gets the policy and grants.

## Adjusting the printed LR

Every position on the printed LR lives in `backend/app/lr/lr_template.json`, in millimetres from the
page's top-left corner. It was measured from a photo, so check it with a test print:

1. Print an LR at **actual size** (not "fit to page") and hold it over a real one against a window.
2. If everything is shifted the same way, the printer is off: change `printer_offset_mm`.
3. If one line or label is off, change its numbers in `lines`, `texts` or `fields`.
4. If the paper is not 210 x 148 mm, change `page`, and the matching size in the app's
   `lr_form_screen.dart`.

Restart the backend after editing.

## Not built yet

- 3D box placement in the load planner, and the comparison with baselines.
- The vision-language model as a second invoice reader, and saving the scanned photos.
- Voice input for chat. A language model is optional and off until `FF_LLM_API_KEY` is set.
- Ordered delivery stops and route planning (the journal's model plugs in here).
- Generating e-way bills on the government portal (needs API access through a GSP).
- A map of truck positions (no GPS feed).
- Scanning PAN cards and multi-page documents; automatic cropping of the photo.
- An SMS and WhatsApp provider (messages are recorded but not sent until one is connected), godown locations.

## Security and testing

- Run the tests: `cd backend && pip install -c constraints.txt -e ".[dev]" && pytest -q` against a PostgreSQL
  16 database whose name ends in `_test` (the suite refuses any other). Set `FF_DATABASE_URL` and
  `FF_MIGRATION_DATABASE_URL` as in `tests/conftest.py`.
- `tests/test_adversarial.py` calls every endpoint without signing in and with hostile input;
  `tests/test_security.py` and `tests/test_concurrency.py` cover sign-in limits, tokens, cross-company
  access and simultaneous requests. Findings and fixes: `docs/AUDIT.md`.
- Dependency versions are pinned in `backend/constraints.txt`; scan with
  `pip-audit -r <(grep -v '^#' backend/constraints.txt) --no-deps --disable-pip`.
- Deploying to the EC2 server behind the DuckDNS name: `docs/DEPLOY.md` (backup first: migrations run on start).
