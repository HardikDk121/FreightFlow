"""Challans: one sealed loading document per loading, so cargo added on the road is traceable."""

import os

from alembic import op

revision = "0007"
down_revision = "0006"

APP_ROLE = os.environ.get("FF_APP_DB_ROLE", "freightflow_app")

SCHEMA = """
ALTER TABLE lr_settings ADD COLUMN next_trip_number integer NOT NULL DEFAULT 1 CHECK (next_trip_number > 0);
ALTER TABLE trip ADD COLUMN trip_no integer;
-- Number the trips that already exist, oldest first, and start each company's counter after them.
UPDATE trip t SET trip_no = n.rn
FROM (SELECT id, row_number() OVER (PARTITION BY company_id ORDER BY dispatched_at) AS rn FROM trip) n
WHERE n.id = t.id;
INSERT INTO lr_settings (company_id)
SELECT DISTINCT company_id FROM trip ON CONFLICT (company_id) DO NOTHING;
UPDATE lr_settings s SET next_trip_number = m.top + 1
FROM (SELECT company_id, max(trip_no) AS top FROM trip GROUP BY company_id) m
WHERE m.company_id = s.company_id;
ALTER TABLE trip ALTER COLUMN trip_no SET NOT NULL;
ALTER TABLE trip ADD CONSTRAINT trip_no_uq UNIQUE (company_id, trip_no);

CREATE TABLE challan (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    trip_id uuid NOT NULL REFERENCES trip (id),
    -- 0 is the primary challan from the origin; 1, 2, 3 are cargo added on the road.
    seq integer NOT NULL CHECK (seq >= 0),
    challan_number text NOT NULL,
    loaded_at text NOT NULL,
    -- For a loading point that is not yet on the route: the stop it comes before.
    insert_before text,
    status text NOT NULL CHECK (status IN ('requested', 'awaiting_driver', 'issued', 'void')),
    -- What was asked for: [{"lr_id": ..., "packages": ...}]. Lines are written only when the driver signs.
    requested_lines jsonb NOT NULL,
    requested_by uuid NOT NULL REFERENCES app_user (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_by uuid REFERENCES app_user (id),
    approved_at timestamptz,
    issued_at timestamptz,
    driver_name text,
    driver_signature jsonb,
    shortage_note text,
    voided_by uuid REFERENCES app_user (id),
    voided_at timestamptz,
    void_reason text,
    -- Hash of this challan's lines chained to the challan issued before it. Null on challans
    -- created for trips that existed before sealing was introduced.
    prev_hash text,
    content_hash text,
    UNIQUE (trip_id, seq),
    UNIQUE (company_id, challan_number),
    UNIQUE (id, trip_id),
    CONSTRAINT challan_maker_checker CHECK (seq = 0 OR approved_by IS NULL OR approved_by <> requested_by),
    CONSTRAINT challan_signed CHECK (seq = 0 OR status <> 'issued' OR driver_signature IS NOT NULL),
    CONSTRAINT challan_void CHECK ((status = 'void') = (voided_at IS NOT NULL AND void_reason IS NOT NULL))
);
CREATE INDEX challan_open_idx ON challan (company_id, status) WHERE status IN ('requested', 'awaiting_driver');

-- Every existing trip gets a primary challan holding its current lines.
INSERT INTO challan (id, company_id, trip_id, seq, challan_number, loaded_at, status, requested_lines,
                     requested_by, created_at, issued_at)
SELECT gen_random_uuid(), t.company_id, t.id, 0, 'CH-' || t.trip_no, 'ORIGIN', 'issued', '[]'::jsonb,
       t.dispatched_by, t.dispatched_at, t.dispatched_at
FROM trip t;

ALTER TABLE dispatch_line ADD COLUMN challan_id uuid;
UPDATE dispatch_line d SET challan_id = c.id FROM challan c WHERE c.trip_id = d.trip_id AND c.seq = 0;
ALTER TABLE dispatch_line ALTER COLUMN challan_id SET NOT NULL;
-- A line's challan must belong to the line's own trip.
ALTER TABLE dispatch_line
    ADD CONSTRAINT dispatch_line_challan_fk FOREIGN KEY (challan_id, trip_id) REFERENCES challan (id, trip_id);
CREATE INDEX dispatch_line_challan_idx ON dispatch_line (challan_id);
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute("ALTER TABLE challan ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON challan "
        "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
    )
    # Sealing is enforced here, not by the application's good behaviour. A challan's number, trip,
    # sequence, requester and requested lines can never be changed; a line can only be marked delivered.
    op.execute(f"GRANT SELECT, INSERT ON challan TO {APP_ROLE}")
    op.execute(
        "GRANT UPDATE (status, approved_by, approved_at, issued_at, driver_name, driver_signature, shortage_note, "
        f"voided_by, voided_at, void_reason, prev_hash, content_hash) ON challan TO {APP_ROLE}"
    )
    op.execute(f"REVOKE UPDATE ON dispatch_line FROM {APP_ROLE}")
    op.execute(f"GRANT UPDATE (delivered_at, delivered_by) ON dispatch_line TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"GRANT UPDATE ON dispatch_line TO {APP_ROLE}")
    op.execute("ALTER TABLE dispatch_line DROP COLUMN challan_id")
    op.execute("DROP TABLE challan")
    op.execute("ALTER TABLE trip DROP COLUMN trip_no")
    op.execute("ALTER TABLE lr_settings DROP COLUMN next_trip_number")
