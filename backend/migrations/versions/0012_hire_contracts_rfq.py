"""Hired trucks and what is paid for them, customer rate contracts, usual transit times, and
requests for quotes from truck owners.

The company owns no trucks: every trip runs on a truck hired from its owner (or through a broker),
whose driver pays diesel, tolls and wages out of the hire. The hire is the largest cost.
"""

import os

from alembic import op

revision = "0012"
down_revision = "0011"

APP_ROLE = os.environ.get("FF_APP_DB_ROLE", "freightflow_app")

SCHEMA = """
CREATE TABLE vendor (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    name text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('truck_owner', 'broker')),
    phone text,
    pan text,
    bank_details text,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX vendor_name_uq ON vendor (company_id, lower(name));

-- Whose truck it is, when known.
ALTER TABLE truck ADD COLUMN vendor_id uuid REFERENCES vendor (id);

-- What was agreed with the truck owner (or broker) for one trip. One per trip.
CREATE TABLE trip_hire (
    trip_id uuid PRIMARY KEY REFERENCES trip (id),
    company_id uuid NOT NULL REFERENCES company (id),
    vendor_id uuid NOT NULL REFERENCES vendor (id),
    hire_amount numeric(12, 2) NOT NULL CHECK (hire_amount > 0),
    rfq_id uuid,
    note text,
    agreed_by uuid NOT NULL REFERENCES app_user (id),
    agreed_at timestamptz NOT NULL DEFAULT now()
);

-- Money paid to the truck owner: insert-only. A mistake is undone by a reversal, with a reason.
CREATE TABLE vendor_payment (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    trip_id uuid NOT NULL REFERENCES trip (id),
    vendor_id uuid NOT NULL REFERENCES vendor (id),
    kind text NOT NULL CHECK (kind IN ('advance', 'balance', 'reversal')),
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    method text NOT NULL CHECK (method IN ('cash', 'upi', 'cheque', 'bank_transfer')),
    reference text,
    note text,
    paid_by uuid NOT NULL REFERENCES app_user (id),
    paid_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT reversal_reason CHECK (kind <> 'reversal' OR note IS NOT NULL)
);
CREATE INDEX vendor_payment_trip_idx ON vendor_payment (trip_id);

-- Taken off what the truck owner is owed: goods short or damaged, late delivery.
CREATE TABLE trip_deduction (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    trip_id uuid NOT NULL REFERENCES trip (id),
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    reason text NOT NULL CHECK (reason IN ('shortage', 'damage', 'late', 'other')),
    note text NOT NULL,
    recorded_by uuid NOT NULL REFERENCES app_user (id),
    recorded_at timestamptz NOT NULL DEFAULT now()
);

-- What the office itself pays for a trip, beyond the hire.
CREATE TABLE trip_expense (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    trip_id uuid NOT NULL REFERENCES trip (id),
    kind text NOT NULL CHECK (kind IN ('loading_labour', 'unloading_labour', 'broker_commission', 'other')),
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    note text,
    recorded_by uuid NOT NULL REFERENCES app_user (id),
    recorded_at timestamptz NOT NULL DEFAULT now()
);

-- A customer's agreed rates for a period.
CREATE TABLE contract (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    party_name text NOT NULL,
    starts_on date NOT NULL,
    ends_on date NOT NULL,
    terms text,
    is_active boolean NOT NULL DEFAULT true,
    created_by uuid NOT NULL REFERENCES app_user (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT contract_dates CHECK (ends_on >= starts_on)
);
CREATE INDEX contract_party_idx ON contract (company_id, lower(party_name));

CREATE TABLE contract_rate (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    contract_id uuid NOT NULL REFERENCES contract (id),
    destination text NOT NULL,
    basis text NOT NULL CHECK (basis IN ('per_kg', 'per_article')),
    rate numeric(10, 2) NOT NULL CHECK (rate > 0),
    UNIQUE (contract_id, destination)
);

-- What the office tells customers a destination usually takes ("Raipur 4 to 5 days"). Not a promise.
CREATE TABLE transit_time (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    destination text NOT NULL,
    days_min integer NOT NULL CHECK (days_min > 0),
    days_max integer NOT NULL,
    CONSTRAINT transit_range CHECK (days_max >= days_min AND days_max <= 60),
    UNIQUE (company_id, destination)
);

-- Asking truck owners and brokers for a price to carry a load. Quotes may be revised (rounds of
-- bidding); the latest quote from each counts, and every revision is kept.
CREATE TABLE rfq (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    branch_id uuid NOT NULL REFERENCES branch (id),
    rfq_number integer NOT NULL,
    origin text NOT NULL,
    destination text NOT NULL,
    weight_kg numeric(10, 2) NOT NULL CHECK (weight_kg > 0),
    truck_type text,
    needed_on date NOT NULL,
    note text,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'awarded', 'cancelled')),
    awarded_quote_id uuid,
    created_by uuid NOT NULL REFERENCES app_user (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz,
    UNIQUE (company_id, rfq_number)
);

CREATE TABLE rfq_invite (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    rfq_id uuid NOT NULL REFERENCES rfq (id),
    vendor_id uuid NOT NULL REFERENCES vendor (id),
    invited_at timestamptz NOT NULL DEFAULT now(),
    last_reminded_at timestamptz,
    UNIQUE (rfq_id, vendor_id)
);

CREATE TABLE rfq_quote (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    rfq_id uuid NOT NULL REFERENCES rfq (id),
    vendor_id uuid NOT NULL REFERENCES vendor (id),
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    vehicle_number text,
    note text,
    recorded_by uuid NOT NULL REFERENCES app_user (id),
    received_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX rfq_quote_rfq_idx ON rfq_quote (rfq_id);

ALTER TABLE trip_hire ADD CONSTRAINT trip_hire_rfq FOREIGN KEY (rfq_id) REFERENCES rfq (id);
ALTER TABLE rfq ADD CONSTRAINT rfq_awarded FOREIGN KEY (awarded_quote_id) REFERENCES rfq_quote (id);
ALTER TABLE lr_settings ADD COLUMN next_rfq_number integer NOT NULL DEFAULT 1;
"""

TABLES = {
    "vendor": "SELECT, INSERT, UPDATE",
    "trip_hire": "SELECT, INSERT",
    "vendor_payment": "SELECT, INSERT",
    "trip_deduction": "SELECT, INSERT",
    "trip_expense": "SELECT, INSERT",
    "contract": "SELECT, INSERT, UPDATE",
    "contract_rate": "SELECT, INSERT, DELETE",
    "transit_time": "SELECT, INSERT, UPDATE, DELETE",
    "rfq": "SELECT, INSERT",
    "rfq_invite": "SELECT, INSERT",
    "rfq_quote": "SELECT, INSERT",
}
COLUMN_UPDATES = {
    "trip_hire": "vendor_id, hire_amount, note",
    "rfq": "status, awarded_quote_id, closed_at",
    "rfq_invite": "last_reminded_at",
}


def upgrade() -> None:
    op.execute(SCHEMA)
    for table, grants in TABLES.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
        )
        op.execute(f"GRANT {grants} ON {table} TO {APP_ROLE}")
    for table, columns in COLUMN_UPDATES.items():
        op.execute(f"GRANT UPDATE ({columns}) ON {table} TO {APP_ROLE}")
    op.execute("CREATE POLICY branch_scope ON rfq AS RESTRICTIVE USING (app_branch_ok(branch_id)) WITH CHECK (app_branch_ok(branch_id))")


def downgrade() -> None:
    op.execute("ALTER TABLE lr_settings DROP COLUMN next_rfq_number")
    op.execute("ALTER TABLE truck DROP COLUMN vendor_id")
    op.execute(
        "DROP TABLE rfq_quote, rfq_invite, trip_hire, rfq, vendor_payment, trip_deduction, trip_expense, "
        "contract_rate, contract, transit_time, vendor CASCADE"
    )
