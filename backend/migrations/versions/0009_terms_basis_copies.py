"""Customer payment terms, LR charge basis, credit overrides on booking, and idempotency keys."""

import os

from alembic import op

revision = "0009"
down_revision = "0008"

APP_ROLE = os.environ.get("FF_APP_DB_ROLE", "freightflow_app")

SCHEMA = """
-- How a customer pays. Customers with no row pay at delivery.
ALTER TABLE credit_terms
    ADD COLUMN payment_terms text NOT NULL DEFAULT 'credit'
        CHECK (payment_terms IN ('advance', 'before_delivery', 'at_delivery', 'credit')),
    ADD COLUMN note text,
    ALTER COLUMN credit_limit DROP NOT NULL,
    ALTER COLUMN credit_days DROP NOT NULL,
    ADD CONSTRAINT credit_terms_shape CHECK (
        (payment_terms = 'credit') = (credit_days IS NOT NULL AND credit_limit IS NOT NULL)
    );

-- When a credit period starts: when the goods are delivered, or when the LR is booked.
ALTER TABLE lr_settings
    ADD COLUMN credit_from text NOT NULL DEFAULT 'delivery' CHECK (credit_from IN ('delivery', 'booking')),
    -- A customer with anything overdue by more than this many days cannot be booked without the owner.
    ADD COLUMN overdue_hold_days integer NOT NULL DEFAULT 15 CHECK (overdue_hold_days BETWEEN 0 AND 365),
    -- Booking holds count only LRs booked from this date. Older LRs may have been paid before the
    -- app recorded payments, so they would block every customer. Null keeps holds off until set.
    ADD COLUMN credit_controls_from date;

-- Per kg, per article, or from the rate matrix. Null on LRs saved before the basis was recorded:
-- their freight stands as entered.
ALTER TABLE lr
    ADD COLUMN charge_basis text CHECK (charge_basis IN ('per_kg', 'per_article', 'matrix')),
    -- Set when the owner let this LR be booked although its payer was over limit or overdue.
    ADD COLUMN credit_override_reason text;

-- A retried request with the same key gets the first answer instead of doing the work twice.
CREATE TABLE idempotency_key (
    company_id uuid NOT NULL REFERENCES company (id),
    key text NOT NULL,
    user_id uuid NOT NULL REFERENCES app_user (id),
    request text NOT NULL,
    status_code integer,
    response jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, key)
);
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute("ALTER TABLE idempotency_key ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON idempotency_key "
        "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
    )
    op.execute(f"GRANT SELECT, INSERT ON idempotency_key TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (status_code, response) ON idempotency_key TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (payment_terms, note) ON credit_terms TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP TABLE idempotency_key")
    op.execute("ALTER TABLE lr DROP COLUMN charge_basis, DROP COLUMN credit_override_reason")
    op.execute("ALTER TABLE lr_settings DROP COLUMN credit_from, DROP COLUMN overdue_hold_days, DROP COLUMN credit_controls_from")
    op.execute("DELETE FROM credit_terms WHERE payment_terms <> 'credit'")
    op.execute(
        "ALTER TABLE credit_terms DROP CONSTRAINT credit_terms_shape, DROP COLUMN payment_terms, DROP COLUMN note, "
        "ALTER COLUMN credit_limit SET NOT NULL, ALTER COLUMN credit_days SET NOT NULL"
    )
