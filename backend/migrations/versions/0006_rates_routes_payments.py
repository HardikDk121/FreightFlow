"""Rate matrix (stations, rate rules), routes and multi-stop trips, truck location, payments."""

import os

from alembic import op

revision = "0006"
down_revision = "0005"

APP_ROLE = os.environ.get("FF_APP_DB_ROLE", "freightflow_app")
NEW_TABLES = ("station", "route", "rate_rule", "payment")

SCHEMA = """
-- A delivery station. `zone` names the base station whose rates apply (Raipur for Jagdalpur);
-- `surcharge_per_kg` is what this station adds on top of the zone's rate (0 for the base itself).
CREATE TABLE station (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    name text NOT NULL,
    zone text NOT NULL,
    surcharge_per_kg numeric(8, 2) NOT NULL DEFAULT 0 CHECK (surcharge_per_kg >= 0),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX station_name_uq ON station (company_id, lower(name));

-- Stations one truck serves in a single run, in the order it reaches them.
CREATE TABLE route (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    name text NOT NULL,
    stops text[] NOT NULL CHECK (cardinality(stops) BETWEEN 1 AND 12),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX route_name_uq ON route (company_id, lower(name));

CREATE TABLE rate_rule (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    goods_class text NOT NULL,
    zone text NOT NULL,
    method text NOT NULL CHECK (method IN ('per_kg', 'per_package_slab', 'per_unit')),
    rate numeric(10, 2) CHECK (rate > 0),
    slabs jsonb,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT rate_rule_shape CHECK ((method = 'per_package_slab') = (slabs IS NOT NULL AND rate IS NULL))
);
CREATE UNIQUE INDEX rate_rule_uq ON rate_rule (company_id, lower(goods_class), lower(zone));

CREATE TABLE payment (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    lr_id uuid NOT NULL REFERENCES lr (id),
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    mode text NOT NULL CHECK (mode IN ('cash', 'upi', 'neft', 'cheque')),
    reference text,
    note text,
    received_on date NOT NULL,
    received_by uuid NOT NULL REFERENCES app_user (id),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX payment_lr_idx ON payment (lr_id);
CREATE INDEX payment_company_date_idx ON payment (company_id, received_on DESC);

ALTER TABLE lr
    ADD COLUMN weight_per_package numeric(8, 2) CHECK (weight_per_package > 0),
    ADD COLUMN rate_rule_id uuid REFERENCES rate_rule (id);

ALTER TABLE truck ADD COLUMN current_station text;

ALTER TABLE trip ADD COLUMN route text[];
UPDATE trip SET route = ARRAY[destination];
ALTER TABLE trip ALTER COLUMN route SET NOT NULL;
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
        )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON station, route, rate_rule TO {APP_ROLE}")
    # A payment is never edited or removed; a mistake is corrected by the owner in the database.
    op.execute(f"GRANT SELECT, INSERT ON payment TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("ALTER TABLE trip DROP COLUMN route")
    op.execute("ALTER TABLE truck DROP COLUMN current_station")
    op.execute("ALTER TABLE lr DROP COLUMN weight_per_package, DROP COLUMN rate_rule_id")
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP TABLE {table}")
