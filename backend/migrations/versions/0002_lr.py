"""LRs and the per-company LR settings (number series, defaults)."""

import os

from alembic import op

revision = "0002"
down_revision = "0001"

APP_ROLE = os.environ.get("FF_APP_DB_ROLE", "freightflow_app")
TABLES = ("lr_settings", "lr")

SCHEMA = """
CREATE TABLE lr_settings (
    company_id uuid PRIMARY KEY REFERENCES company (id),
    prefix text NOT NULL DEFAULT 'LR' CHECK (prefix ~ '^[A-Z0-9]{1,8}$'),
    next_number integer NOT NULL DEFAULT 1 CHECK (next_number > 0),
    from_city text,
    default_st_charges numeric(10, 2) NOT NULL DEFAULT 0 CHECK (default_st_charges >= 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE lr (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    prefix text NOT NULL,
    series_no integer NOT NULL CHECK (series_no > 0),
    lr_number text NOT NULL,
    status text NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'cancelled')),
    lr_date date NOT NULL,
    from_city text NOT NULL,
    to_city text NOT NULL,
    freight_by text NOT NULL CHECK (freight_by IN ('ToPay', 'Paid', 'TBB')),
    consignor_name text NOT NULL,
    consignor_gstin text,
    consignee_name text NOT NULL,
    consignee_gstin text,
    goods_description text NOT NULL,
    packages integer NOT NULL CHECK (packages > 0),
    weight numeric(8, 2) CHECK (weight >= 0),
    charged_weight numeric(8, 2) CHECK (charged_weight >= 0),
    rate numeric(10, 2) NOT NULL DEFAULT 0 CHECK (rate >= 0),
    freight numeric(10, 2) NOT NULL DEFAULT 0 CHECK (freight >= 0),
    hamali numeric(10, 2) NOT NULL DEFAULT 0 CHECK (hamali >= 0),
    other_charges numeric(10, 2) NOT NULL DEFAULT 0 CHECK (other_charges >= 0),
    st_charges numeric(10, 2) NOT NULL DEFAULT 0 CHECK (st_charges >= 0),
    total numeric(12, 2) GENERATED ALWAYS AS (freight + hamali + other_charges + st_charges) STORED,
    value numeric(12, 2) CHECK (value >= 0),
    eway_bill_no text CHECK (eway_bill_no ~ '^[0-9]{12}$'),
    created_by uuid NOT NULL REFERENCES app_user (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    cancelled_by uuid REFERENCES app_user (id),
    cancelled_at timestamptz,
    cancel_reason text,
    UNIQUE (company_id, prefix, series_no),
    UNIQUE (company_id, lr_number),
    CONSTRAINT lr_cancel_fields CHECK (
        (status = 'cancelled') = (cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL AND cancel_reason IS NOT NULL)
    )
);
CREATE INDEX lr_company_created_idx ON lr (company_id, created_at DESC);
CREATE INDEX lr_consignor_gstin_idx ON lr (company_id, consignor_gstin, created_at DESC);
CREATE INDEX lr_consignor_name_idx ON lr (company_id, lower(consignor_name), created_at DESC);
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
        )
    # No DELETE: an LR is cancelled, never removed, so every number stays accounted for.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {', '.join(TABLES)} TO {APP_ROLE}")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table}")
