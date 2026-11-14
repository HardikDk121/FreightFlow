# FreightFlow AI

Slice 1 of the system architecture: accounts, tenancy and master data.

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

## Rules the code relies on

- **One transaction per request.** `get_session` commits on success and rolls back on any exception.
- **Tenant scope.** `current_user` calls `set_tenant`, and every table has a row-level security policy on `company_id`. A query that forgets its company filter still returns only the caller's rows.
- **Two database roles.** Migrations run as `freightflow_owner`. The API runs as `freightflow_app`, which has no DELETE on any table and no UPDATE on `audit_log`.
- **Deactivate, never delete.** There are no DELETE endpoints. Use `PATCH` with `is_active: false`.
- **Module shape.** Each module is `schemas.py`, `service.py`, `router.py`. Routers hold no logic. Modules call each other only through `service`.
- **Adding a tenant table.** Add it to `TENANT_TABLES` in a new migration so it gets the policy and grants.

## Not in this slice

- Forgot-password by email. An admin can reset a staff password meanwhile.
- Godown locations on the company.
- The home dashboard, which needs consignments.
