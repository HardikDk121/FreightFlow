"""Collection controls: money receipts, visits, collections, cash custody, handovers, deposits,
bank statement lines, shortages, standing credit, release approvals and gate passes.

Replaces the single-step `payment` table: its rows become collections marked `legacy`, so history
is kept but never presented as verified.
"""

import os

from alembic import op

revision = "0008"
down_revision = "0007"

APP_ROLE = os.environ.get("FF_APP_DB_ROLE", "freightflow_app")

ROLES = """
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'collector';
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'register_clerk';
"""

SCHEMA = """
-- Printed on every money receipt so customers pay into the company account, never a person's.
ALTER TABLE company ADD COLUMN bank_details text;

ALTER TABLE lr_settings
    ADD COLUMN next_receipt_number integer NOT NULL DEFAULT 1 CHECK (next_receipt_number > 0),
    ADD COLUMN next_gate_pass_number integer NOT NULL DEFAULT 1 CHECK (next_gate_pass_number > 0),
    ADD COLUMN next_deposit_number integer NOT NULL DEFAULT 1 CHECK (next_deposit_number > 0),
    -- Most cash a collector (not the owner) may take against one receipt.
    ADD COLUMN collector_cash_limit numeric(12, 2) NOT NULL DEFAULT 25000 CHECK (collector_cash_limit > 0);

CREATE TABLE money_receipt (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    receipt_number text NOT NULL,
    payer_name text NOT NULL,
    payer_phone text,
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    status text NOT NULL CHECK (status IN ('open', 'settled', 'cancelled')),
    -- sha256 of the token printed in the verification QR; the token itself is never stored.
    verify_hash text NOT NULL UNIQUE,
    issued_by uuid NOT NULL REFERENCES app_user (id),
    issued_at timestamptz NOT NULL DEFAULT now(),
    cancelled_by uuid REFERENCES app_user (id),
    cancelled_at timestamptz,
    cancel_reason text,
    UNIQUE (company_id, receipt_number),
    CONSTRAINT money_receipt_cancel CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL AND cancel_reason IS NOT NULL))
);

CREATE TABLE money_receipt_line (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    receipt_id uuid NOT NULL REFERENCES money_receipt (id),
    lr_id uuid NOT NULL REFERENCES lr (id),
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    UNIQUE (receipt_id, lr_id)
);
CREATE INDEX money_receipt_line_lr_idx ON money_receipt_line (lr_id);

CREATE TABLE collection_visit (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    receipt_id uuid NOT NULL REFERENCES money_receipt (id),
    collector_id uuid NOT NULL REFERENCES app_user (id),
    visited_at timestamptz NOT NULL DEFAULT now(),
    outcome text NOT NULL CHECK (outcome IN ('paid', 'part_paid', 'come_later', 'refused')),
    promised_on date,
    note text,
    CONSTRAINT visit_promise CHECK ((outcome = 'come_later') = (promised_on IS NOT NULL))
);
CREATE INDEX collection_visit_receipt_idx ON collection_visit (receipt_id, visited_at DESC);

CREATE TABLE cash_handover (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    from_user uuid NOT NULL REFERENCES app_user (id),
    to_user uuid NOT NULL REFERENCES app_user (id),
    expected_cash numeric(12, 2) NOT NULL CHECK (expected_cash >= 0),
    counted_cash numeric(12, 2) NOT NULL CHECK (counted_cash >= 0 AND counted_cash <= expected_cash),
    handed_at timestamptz NOT NULL DEFAULT now(),
    from_confirmed_at timestamptz,
    deposit_id uuid,
    CONSTRAINT handover_two_people CHECK (from_user <> to_user)
);

CREATE TABLE bank_deposit (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    deposit_number text NOT NULL,
    depositor uuid NOT NULL REFERENCES app_user (id),
    expected_cash numeric(12, 2) NOT NULL CHECK (expected_cash >= 0),
    cash_amount numeric(12, 2) NOT NULL CHECK (cash_amount >= 0 AND cash_amount <= expected_cash),
    slip_reference text,
    deposited_at timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL DEFAULT 'in_transit' CHECK (status IN ('in_transit', 'banked')),
    bank_line_id uuid,
    UNIQUE (company_id, deposit_number)
);
ALTER TABLE cash_handover ADD CONSTRAINT cash_handover_deposit_fk FOREIGN KEY (deposit_id) REFERENCES bank_deposit (id);

CREATE TABLE bank_import (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    file_name text NOT NULL,
    lines_read integer NOT NULL,
    lines_new integer NOT NULL,
    imported_by uuid NOT NULL REFERENCES app_user (id),
    imported_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bank_statement_line (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    import_id uuid NOT NULL REFERENCES bank_import (id),
    txn_date date NOT NULL,
    narration text NOT NULL,
    reference text,
    -- Reference numbers found in the narration and reference columns (UPI RRNs, NEFT/RTGS UTRs).
    refs text NOT NULL DEFAULT '',
    credit numeric(14, 2) NOT NULL DEFAULT 0 CHECK (credit >= 0),
    debit numeric(14, 2) NOT NULL DEFAULT 0 CHECK (debit >= 0),
    balance numeric(14, 2),
    row_hash text NOT NULL,
    status text NOT NULL DEFAULT 'unmatched' CHECK (status IN ('unmatched', 'matched', 'ignored')),
    matched_kind text CHECK (matched_kind IN ('collection', 'deposit', 'allocation')),
    decided_by uuid REFERENCES app_user (id),
    note text,
    UNIQUE (company_id, row_hash)
);
CREATE INDEX bank_statement_line_open_idx ON bank_statement_line (company_id, status, txn_date);
ALTER TABLE bank_deposit ADD CONSTRAINT bank_deposit_line_fk FOREIGN KEY (bank_line_id) REFERENCES bank_statement_line (id);

-- How this company's statement file is laid out, learnt from the first import.
CREATE TABLE statement_format (
    company_id uuid PRIMARY KEY REFERENCES company (id),
    columns jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE collection (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    receipt_id uuid REFERENCES money_receipt (id),
    visit_id uuid REFERENCES collection_visit (id),
    payer_name text NOT NULL,
    method text NOT NULL CHECK (method IN ('cash', 'upi', 'cheque', 'bank_transfer')),
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    utr text,
    cheque_number text,
    cheque_bank text,
    cheque_date date,
    collected_by uuid NOT NULL REFERENCES app_user (id),
    collected_at timestamptz NOT NULL DEFAULT now(),
    -- pending until the bank shows the money; legacy for payments recorded before these controls.
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'failed', 'legacy')),
    confirmed_at timestamptz,
    bank_line_id uuid REFERENCES bank_statement_line (id),
    handover_id uuid REFERENCES cash_handover (id),
    deposit_id uuid REFERENCES bank_deposit (id),
    failed_reason text,
    CONSTRAINT collection_upi_utr CHECK (method <> 'upi' OR status = 'legacy' OR utr ~ '^[0-9]{12}$'),
    CONSTRAINT collection_cheque CHECK (method <> 'cheque' OR status = 'legacy' OR (cheque_number IS NOT NULL AND cheque_bank IS NOT NULL)),
    CONSTRAINT collection_failed CHECK ((status = 'failed') = (failed_reason IS NOT NULL))
);
-- A UPI reference or a cheque can be recorded once, so one payment cannot settle two receipts.
CREATE UNIQUE INDEX collection_utr_uq ON collection (company_id, utr) WHERE utr IS NOT NULL AND status <> 'failed';
CREATE UNIQUE INDEX collection_cheque_uq ON collection (company_id, cheque_bank, cheque_number)
    WHERE cheque_number IS NOT NULL AND status <> 'failed';
CREATE INDEX collection_custody_idx ON collection (company_id, collected_by) WHERE handover_id IS NULL AND deposit_id IS NULL;

CREATE TABLE collection_allocation (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    collection_id uuid NOT NULL REFERENCES collection (id),
    lr_id uuid NOT NULL REFERENCES lr (id),
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    UNIQUE (collection_id, lr_id)
);
CREATE INDEX collection_allocation_lr_idx ON collection_allocation (lr_id);

CREATE TABLE shortage (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    user_id uuid NOT NULL REFERENCES app_user (id),
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    source text NOT NULL CHECK (source IN ('handover', 'deposit')),
    source_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'recover_from_salary', 'written_off', 'found')),
    salary_month date,
    decided_by uuid REFERENCES app_user (id),
    decided_at timestamptz,
    note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT shortage_salary CHECK ((status = 'recover_from_salary') = (salary_month IS NOT NULL))
);

CREATE TABLE credit_terms (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    payer_name text NOT NULL,
    credit_limit numeric(12, 2) NOT NULL CHECK (credit_limit > 0),
    credit_days integer NOT NULL CHECK (credit_days BETWEEN 1 AND 365),
    is_active boolean NOT NULL DEFAULT true,
    approved_by uuid NOT NULL REFERENCES app_user (id),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX credit_terms_payer_uq ON credit_terms (company_id, lower(payer_name));

CREATE TABLE release_approval (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    lr_id uuid NOT NULL UNIQUE REFERENCES lr (id),
    reason text NOT NULL,
    approved_by uuid NOT NULL REFERENCES app_user (id),
    approved_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE gate_pass (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    gate_pass_number text NOT NULL,
    lr_id uuid NOT NULL UNIQUE REFERENCES lr (id),
    -- Why the goods could leave: paid, standing credit, a one-off approval, or not a to-pay LR.
    basis text NOT NULL CHECK (basis IN ('paid', 'credit', 'approved', 'not_to_pay')),
    issued_by uuid NOT NULL REFERENCES app_user (id),
    issued_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (company_id, gate_pass_number)
);

CREATE TABLE customer_notice (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    collection_id uuid NOT NULL REFERENCES collection (id),
    channel text NOT NULL CHECK (channel IN ('sms', 'whatsapp')),
    phone text NOT NULL,
    body text NOT NULL,
    status text NOT NULL CHECK (status IN ('sent', 'not_sent')),
    reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Payments recorded before these controls: kept as legacy collections, never shown as bank-confirmed.
INSERT INTO collection (id, company_id, payer_name, method, amount, utr, collected_by, collected_at, status)
SELECT p.id, p.company_id,
       CASE WHEN l.freight_by = 'ToPay' THEN l.consignee_name ELSE l.consignor_name END,
       CASE p.mode WHEN 'neft' THEN 'bank_transfer' ELSE p.mode END,
       p.amount, NULL, p.received_by, p.created_at, 'legacy'
FROM payment p JOIN lr l ON l.id = p.lr_id;
INSERT INTO collection_allocation (id, company_id, collection_id, lr_id, amount)
SELECT gen_random_uuid(), p.company_id, p.id, p.lr_id, p.amount FROM payment p;
DROP TABLE payment;
"""

TABLES = (
    "money_receipt", "money_receipt_line", "collection_visit", "cash_handover", "bank_deposit", "bank_import",
    "bank_statement_line", "statement_format", "collection", "collection_allocation", "shortage", "credit_terms",
    "release_approval", "gate_pass", "customer_notice",
)

# Everything is insert-only for the API except the columns that record what happened next.
UPDATABLE = {
    "money_receipt": "status, cancelled_by, cancelled_at, cancel_reason",
    "cash_handover": "from_confirmed_at, deposit_id",
    "bank_deposit": "status, bank_line_id",
    "bank_statement_line": "status, matched_kind, decided_by, note",
    "statement_format": "columns, updated_at",
    "bank_import": "lines_new",
    "collection": "status, confirmed_at, bank_line_id, handover_id, deposit_id, failed_reason",
    "shortage": "status, salary_month, decided_by, decided_at, note",
    "credit_terms": "credit_limit, credit_days, is_active, approved_by, updated_at",
}

# Receipt verification without signing in: one lookup across companies, returning ids only.
VERIFY_FN = """
CREATE FUNCTION receipt_by_verify_hash(p_hash text)
RETURNS TABLE (id uuid, company_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ SELECT r.id, r.company_id FROM money_receipt r WHERE r.verify_hash = p_hash $$;
REVOKE ALL ON FUNCTION receipt_by_verify_hash(text) FROM PUBLIC;
"""


def upgrade() -> None:
    op.execute(ROLES)
    op.execute(SCHEMA)
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
        )
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")
        if table in UPDATABLE:
            op.execute(f"GRANT UPDATE ({UPDATABLE[table]}) ON {table} TO {APP_ROLE}")
    op.execute(VERIFY_FN)
    op.execute(f"GRANT EXECUTE ON FUNCTION receipt_by_verify_hash(text) TO {APP_ROLE}")


def downgrade() -> None:
    raise NotImplementedError("Collections replace the payment table; restore from a backup to go back.")
