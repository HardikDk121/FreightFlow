# FreightFlow AI

Accounts, master data, LRs with invoice scan and printing, pending goods, load planning, trips, delivery, chat and dashboard.

- `backend/`: FastAPI and PostgreSQL. Tested.
- `app/`: Flutter app for the same slice. Not compiled; see `app/README.md`.

The rest of this file covers the backend.

## What is in this slice

| Area | Endpoints |
| --- | --- |
| Auth | `POST /auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/invites/accept` |
| Profile | `GET /me`, `PATCH /me`, `POST /me/password` |
| Users (admin) | `GET /users`, `POST /users/invites`, `PATCH /users/{id}`, `POST /users/{id}/password` |
| Company | `GET /company`, `PATCH /company` (admin) |
| Master data | `/parties`, `/item-types`, `/trucks`: list, get, create, update. Admin and manager write; everyone reads. |
| LRs | `POST /lrs` saves with the next number; `GET /lrs`, `GET /lrs/{id}`, `GET /lrs/{id}/pdf` (reprint); `POST /lrs/{id}/cancel` (admin, manager). A saved LR is never edited. |
| LR form helpers | `GET /lrs/defaults` (provisional number, from city, ST. charges), `GET /lrs/suggestions` (the consignor's last LR), `POST /lrs/print-preview` (PDF, nothing saved) |
| LR settings | `GET /lrs/settings`, `PATCH /lrs/settings` (admin): number prefix and next number, from city, default ST. charges |
| Invoice scan | `POST /invoices/scan` (photo upload): reads consignor, consignee, GST numbers, city, goods, value and e-way bill number. Nothing is saved and the photo is not kept. |
| Pending | `GET /pending` (by destination), `GET /pending/lrs?destination=&older_than_days=` (oldest first) |
| Trips | `POST /trips/plan` (load suggestion), `POST /trips` (dispatch, partial loads allowed), `GET /trips`, `GET /trips/{id}`, `POST /trips/{id}/lines/{line_id}/deliver` |
| Chat | `POST /chat`: answers from five read-only tools; refuses anything that would change data; every question is audited |
| Dashboard | `GET /dashboard` |
| Ops | `GET /health` |

Interactive API docs are at `/docs` once the server is running.

## Run it

```
cp .env.example .env      # then replace every value
docker compose up --build
```

The API listens on port 8000. Migrations run on start.

## Run the tests

The tests need a real PostgreSQL 16, because they check row-level security and table privileges.

```
psql -U postgres -c "CREATE ROLE freightflow_owner LOGIN PASSWORD 'owner' CREATEDB"
psql -U postgres -c "CREATE ROLE freightflow_app LOGIN PASSWORD 'app'"
psql -U postgres -c "CREATE DATABASE freightflow_test OWNER freightflow_owner"
cd backend
pip install -e ".[dev]"
pytest
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
- **Chat** picks a tool with keyword rules in `app/chat/interpreter.py` (English only). A language model
  can replace that one function without touching the tools, permissions or audit log.
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
- A language model and voice input for chat; Hindi and Gujarati questions.
- Ordered delivery stops and route planning (the journal's model plugs in here).
- Forgot-password by email, godown locations, finance (freight collection, trip expenses, profit).
