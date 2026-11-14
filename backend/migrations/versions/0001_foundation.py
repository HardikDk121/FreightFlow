"""Foundation: tenancy, accounts, master data, audit log."""

import os

from alembic import op

revision = "0001"
down_revision = None

APP_ROLE = os.environ.get("FF_APP_DB_ROLE", "freightflow_app")
TENANT_TABLES = ("app_user", "auth_token", "user_invite", "party", "item_type", "truck", "audit_log")

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TYPE user_role AS ENUM ('admin', 'manager', 'dispatcher', 'clerk');

-- Company of the current transaction, set by the API on every request. NULL when unset.
CREATE FUNCTION app_company_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.company_id', true), '')::uuid $$;

CREATE TABLE company (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    address text,
    gstin text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app_user (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    name text NOT NULL,
    email citext NOT NULL UNIQUE,
    phone text UNIQUE,
    password_hash text NOT NULL,
    role user_role NOT NULL,
    language text NOT NULL DEFAULT 'en' CHECK (language IN ('en', 'hi', 'gu')),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX app_user_company_idx ON app_user (company_id);

CREATE TABLE auth_token (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    user_id uuid NOT NULL REFERENCES app_user (id),
    token_hash text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    rotated boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auth_token_user_idx ON auth_token (user_id) WHERE revoked_at IS NULL;

CREATE TABLE user_invite (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    email citext NOT NULL,
    role user_role NOT NULL,
    token_hash text NOT NULL UNIQUE,
    invited_by uuid NOT NULL REFERENCES app_user (id),
    expires_at timestamptz NOT NULL,
    accepted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE party (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    name text NOT NULL,
    address text,
    gstin text,
    phone text,
    latitude numeric(9, 6) CHECK (latitude BETWEEN -90 AND 90),
    longitude numeric(9, 6) CHECK (longitude BETWEEN -180 AND 180),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT party_coordinates_together CHECK ((latitude IS NULL) = (longitude IS NULL))
);
CREATE UNIQUE INDEX party_name_uq ON party (company_id, lower(name));

CREATE TABLE item_type (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    name text NOT NULL,
    length_cm numeric(10, 2) NOT NULL CHECK (length_cm > 0),
    width_cm numeric(10, 2) NOT NULL CHECK (width_cm > 0),
    height_cm numeric(10, 2) NOT NULL CHECK (height_cm > 0),
    unit_weight_kg numeric(10, 2) NOT NULL CHECK (unit_weight_kg > 0),
    stackable boolean NOT NULL DEFAULT true,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX item_type_name_uq ON item_type (company_id, lower(name));

CREATE TABLE truck (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    vehicle_number text NOT NULL,
    label text,
    inner_length_cm numeric(10, 2) NOT NULL CHECK (inner_length_cm > 0),
    inner_width_cm numeric(10, 2) NOT NULL CHECK (inner_width_cm > 0),
    inner_height_cm numeric(10, 2) NOT NULL CHECK (inner_height_cm > 0),
    payload_kg numeric(10, 2) NOT NULL CHECK (payload_kg > 0),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (company_id, vehicle_number)
);

CREATE TABLE audit_log (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    actor_id uuid REFERENCES app_user (id),
    action text NOT NULL,
    entity text NOT NULL,
    entity_id text NOT NULL,
    detail jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_company_time_idx ON audit_log (company_id, created_at DESC);

-- Login happens before the caller's company is known, so this one lookup crosses
-- companies. It runs as the table owner and returns ids only.
CREATE FUNCTION auth_user_by_login(p_login text)
RETURNS TABLE (id uuid, company_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ SELECT u.id, u.company_id FROM app_user u WHERE u.email = p_login::citext OR u.phone = p_login $$;
REVOKE ALL ON FUNCTION auth_user_by_login(text) FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(SCHEMA)

    op.execute("ALTER TABLE company ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON company "
        "USING (id = app_company_id()) WITH CHECK (id = app_company_id())"
    )
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
        )

    # No DELETE anywhere: rows are deactivated or revoked. The audit log is insert-only.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    writable = ", ".join(("company", *(t for t in TENANT_TABLES if t != "audit_log")))
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {writable} TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON audit_log TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION auth_user_by_login(text) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION auth_user_by_login(text)")
    for table in (*reversed(TENANT_TABLES), "company"):
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP FUNCTION app_company_id()")
    op.execute("DROP TYPE user_role")
