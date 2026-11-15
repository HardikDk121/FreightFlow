"""Trips, dispatch lines, and the item type of an LR's packages (for load planning)."""

import os

from alembic import op

revision = "0003"
down_revision = "0002"

APP_ROLE = os.environ.get("FF_APP_DB_ROLE", "freightflow_app")
TABLES = ("trip", "dispatch_line")

SCHEMA = """
ALTER TABLE lr ADD COLUMN item_type_id uuid REFERENCES item_type (id);

CREATE TABLE trip (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    truck_id uuid NOT NULL REFERENCES truck (id),
    destination text NOT NULL,
    driver_name text,
    driver_phone text,
    status text NOT NULL DEFAULT 'dispatched' CHECK (status IN ('dispatched', 'completed')),
    dispatched_by uuid NOT NULL REFERENCES app_user (id),
    dispatched_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CONSTRAINT trip_completed CHECK ((status = 'completed') = (completed_at IS NOT NULL))
);
CREATE INDEX trip_company_time_idx ON trip (company_id, dispatched_at DESC);
-- A truck can be on one undelivered trip at a time.
CREATE UNIQUE INDEX trip_one_open_per_truck ON trip (truck_id) WHERE status = 'dispatched';

CREATE TABLE dispatch_line (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    trip_id uuid NOT NULL REFERENCES trip (id),
    lr_id uuid NOT NULL REFERENCES lr (id),
    packages integer NOT NULL CHECK (packages > 0),
    delivered_at timestamptz,
    delivered_by uuid REFERENCES app_user (id),
    UNIQUE (trip_id, lr_id),
    CONSTRAINT dispatch_line_delivered CHECK ((delivered_at IS NULL) = (delivered_by IS NULL))
);
CREATE INDEX dispatch_line_lr_idx ON dispatch_line (lr_id);
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
        )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {', '.join(TABLES)} TO {APP_ROLE}")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table}")
    op.execute("ALTER TABLE lr DROP COLUMN item_type_id")
