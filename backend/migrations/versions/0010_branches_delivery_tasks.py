"""Branches and branch-scoped data, configurable permissions, gate passes with proof of delivery,
destination charges on money receipts, collection tasks, reminders and approval requests."""

import os

from alembic import op

revision = "0010"
down_revision = "0009"

APP_ROLE = os.environ.get("FF_APP_DB_ROLE", "freightflow_app")

ROLES = "ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'accountant';"

SCHEMA = """
CREATE TABLE branch (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    name text NOT NULL,
    address text,
    phone text,
    -- Destination cities this branch delivers to: an LR to one of them is this branch's to deliver.
    cities text[] NOT NULL DEFAULT '{}',
    is_head_office boolean NOT NULL DEFAULT false,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX branch_name_uq ON branch (company_id, lower(name));
CREATE UNIQUE INDEX branch_head_office_uq ON branch (company_id) WHERE is_head_office;

-- Every company starts with one head office holding everything that exists today.
INSERT INTO branch (id, company_id, name, is_head_office)
SELECT gen_random_uuid(), c.id, 'Head office', true FROM company c;

-- A user with no branch works across all branches. Permissions add to or take away from the role's.
ALTER TABLE app_user
    ADD COLUMN branch_id uuid REFERENCES branch (id),
    ADD COLUMN permissions_granted text[] NOT NULL DEFAULT '{}',
    ADD COLUMN permissions_revoked text[] NOT NULL DEFAULT '{}';
UPDATE app_user u SET branch_id = b.id FROM branch b
WHERE b.company_id = u.company_id AND b.is_head_office AND u.role <> 'admin';
ALTER TABLE user_invite ADD COLUMN branch_id uuid REFERENCES branch (id);

-- Booking branch, and the branch that delivers (from the destination city).
ALTER TABLE lr ADD COLUMN branch_id uuid REFERENCES branch (id), ADD COLUMN delivery_branch_id uuid REFERENCES branch (id);
UPDATE lr l SET branch_id = b.id FROM branch b WHERE b.company_id = l.company_id AND b.is_head_office;
ALTER TABLE lr ALTER COLUMN branch_id SET NOT NULL;
CREATE INDEX lr_delivery_branch_idx ON lr (delivery_branch_id);

ALTER TABLE trip ADD COLUMN branch_id uuid REFERENCES branch (id), ADD COLUMN stop_branch_ids uuid[] NOT NULL DEFAULT '{}';
UPDATE trip t SET branch_id = b.id FROM branch b WHERE b.company_id = t.company_id AND b.is_head_office;
ALTER TABLE trip ALTER COLUMN branch_id SET NOT NULL;

ALTER TABLE money_receipt ADD COLUMN branch_id uuid REFERENCES branch (id);
ALTER TABLE collection ADD COLUMN branch_id uuid REFERENCES branch (id);
ALTER TABLE cash_handover ADD COLUMN branch_id uuid REFERENCES branch (id);
ALTER TABLE bank_deposit ADD COLUMN branch_id uuid REFERENCES branch (id);
ALTER TABLE shortage ADD COLUMN branch_id uuid REFERENCES branch (id);
UPDATE money_receipt x SET branch_id = b.id FROM branch b WHERE b.company_id = x.company_id AND b.is_head_office;
UPDATE collection x SET branch_id = b.id FROM branch b WHERE b.company_id = x.company_id AND b.is_head_office;
UPDATE cash_handover x SET branch_id = b.id FROM branch b WHERE b.company_id = x.company_id AND b.is_head_office;
UPDATE bank_deposit x SET branch_id = b.id FROM branch b WHERE b.company_id = x.company_id AND b.is_head_office;
UPDATE shortage x SET branch_id = b.id FROM branch b WHERE b.company_id = x.company_id AND b.is_head_office;
ALTER TABLE money_receipt ALTER COLUMN branch_id SET NOT NULL;
ALTER TABLE collection ALTER COLUMN branch_id SET NOT NULL;
ALTER TABLE cash_handover ALTER COLUMN branch_id SET NOT NULL;
ALTER TABLE bank_deposit ALTER COLUMN branch_id SET NOT NULL;
ALTER TABLE shortage ALTER COLUMN branch_id SET NOT NULL;

-- Numbering that can continue a paper series: "44005" (no prefix) or "GP-12".
ALTER TABLE lr_settings
    ADD COLUMN receipt_prefix text NOT NULL DEFAULT 'MR',
    ADD COLUMN gate_pass_prefix text NOT NULL DEFAULT 'GP';

-- Charges added at the destination on the money receipt (labour, door delivery, demurrage).
-- They count as owed only while their receipt is not cancelled.
CREATE TABLE lr_charge (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    lr_id uuid NOT NULL REFERENCES lr (id),
    receipt_id uuid NOT NULL REFERENCES money_receipt (id),
    kind text NOT NULL CHECK (kind IN ('labour', 'dc_charge', 'demurrage')),
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    added_by uuid NOT NULL REFERENCES app_user (id),
    added_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (receipt_id, lr_id, kind)
);
CREATE INDEX lr_charge_lr_idx ON lr_charge (lr_id);

-- The gate pass as on paper: one consignee, several LRs, the local vehicle and its driver,
-- and the consignee's signature as proof of delivery.
ALTER TABLE gate_pass
    ADD COLUMN branch_id uuid REFERENCES branch (id),
    ADD COLUMN consignee_name text,
    ADD COLUMN auto_no text,
    ADD COLUMN driver_name text,
    ADD COLUMN status text NOT NULL DEFAULT 'issued' CHECK (status IN ('issued', 'delivered', 'void')),
    -- Proof of delivery
    ADD COLUMN delivered_at timestamptz,
    ADD COLUMN pod_received_at timestamptz,
    ADD COLUMN receiver_name text,
    ADD COLUMN receiver_phone text,
    ADD COLUMN signature jsonb,
    ADD COLUMN photo bytea,
    ADD COLUMN latitude double precision,
    ADD COLUMN longitude double precision,
    ADD COLUMN accuracy_m double precision,
    ADD COLUMN pod_recorded_by uuid REFERENCES app_user (id),
    ADD COLUMN void_reason text,
    ADD COLUMN voided_by uuid REFERENCES app_user (id),
    ADD COLUMN voided_at timestamptz;

CREATE TABLE gate_pass_line (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    gate_pass_id uuid NOT NULL REFERENCES gate_pass (id),
    lr_id uuid NOT NULL REFERENCES lr (id),
    packages integer NOT NULL CHECK (packages > 0),
    -- Why the goods could leave: paid, credit, approved, not_to_pay. Printed in the "Paymats" column.
    basis text NOT NULL CHECK (basis IN ('paid', 'credit', 'approved', 'not_to_pay')),
    UNIQUE (gate_pass_id, lr_id)
);
CREATE INDEX gate_pass_line_lr_idx ON gate_pass_line (lr_id);

INSERT INTO gate_pass_line (id, company_id, gate_pass_id, lr_id, packages, basis)
SELECT gen_random_uuid(), g.company_id, g.id, g.lr_id, l.packages, g.basis FROM gate_pass g JOIN lr l ON l.id = g.lr_id;
UPDATE gate_pass g SET consignee_name = l.consignee_name, branch_id = l.branch_id FROM lr l WHERE l.id = g.lr_id;
ALTER TABLE gate_pass DROP COLUMN lr_id, DROP COLUMN basis;
ALTER TABLE gate_pass ALTER COLUMN branch_id SET NOT NULL, ALTER COLUMN consignee_name SET NOT NULL;
ALTER TABLE gate_pass ADD CONSTRAINT gate_pass_pod CHECK (
    status <> 'delivered' OR (delivered_at IS NOT NULL AND receiver_name IS NOT NULL AND signature IS NOT NULL)
);
ALTER TABLE gate_pass ADD CONSTRAINT gate_pass_void CHECK ((status = 'void') = (voided_at IS NOT NULL AND void_reason IS NOT NULL));

CREATE TABLE collection_task (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    branch_id uuid NOT NULL REFERENCES branch (id),
    payer_name text NOT NULL,
    assigned_to uuid REFERENCES app_user (id),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'promised', 'done', 'cancelled')),
    amount_due numeric(12, 2) NOT NULL,
    oldest_due date NOT NULL,
    -- When someone must act next: today for a new task, the promised date after a promise.
    next_action_on date NOT NULL,
    created_on date NOT NULL,
    last_attempt_at timestamptz,
    closed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX collection_task_open_uq ON collection_task (company_id, branch_id, lower(payer_name))
    WHERE status IN ('open', 'promised');

CREATE TABLE task_attempt (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    task_id uuid NOT NULL REFERENCES collection_task (id),
    user_id uuid NOT NULL REFERENCES app_user (id),
    outcome text NOT NULL CHECK (outcome IN ('called', 'visited', 'not_available', 'promised', 'refused', 'paid')),
    promised_on date,
    note text,
    attempted_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT attempt_promise CHECK ((outcome = 'promised') = (promised_on IS NOT NULL))
);

CREATE TABLE reminder (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    payer_name text NOT NULL,
    phone text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('before_due', 'due', 'overdue')),
    channel text NOT NULL CHECK (channel IN ('sms', 'whatsapp')),
    amount numeric(12, 2) NOT NULL,
    body text NOT NULL,
    status text NOT NULL CHECK (status IN ('sent', 'not_sent')),
    reason text,
    sent_on date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX reminder_once_uq ON reminder (company_id, lower(payer_name), kind, channel, sent_on);

-- Customers can be left out of automatic reminders.
ALTER TABLE credit_terms ADD COLUMN reminders boolean NOT NULL DEFAULT true;

CREATE TABLE approval_request (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    branch_id uuid NOT NULL REFERENCES branch (id),
    kind text NOT NULL CHECK (kind IN ('release')),
    lr_id uuid NOT NULL REFERENCES lr (id),
    reason text NOT NULL,
    requested_by uuid NOT NULL REFERENCES app_user (id),
    requested_at timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    decided_by uuid REFERENCES app_user (id),
    decided_at timestamptz,
    decision_note text
);
CREATE UNIQUE INDEX approval_request_pending_uq ON approval_request (lr_id, kind) WHERE status = 'pending';

-- Which branches this request may see: 'all', or a comma-separated list of branch ids.
CREATE FUNCTION app_branch_ok(b uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT coalesce(current_setting('app.branches', true), '') = 'all'
        OR (b IS NOT NULL AND b::text = ANY (string_to_array(coalesce(current_setting('app.branches', true), ''), ',')))
$$;
-- For the daily job: which companies exist. Ids only, like the sign-in lookup.
CREATE FUNCTION all_company_ids() RETURNS SETOF uuid LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = public, pg_temp AS $$ SELECT id FROM company $$;
REVOKE ALL ON FUNCTION all_company_ids() FROM PUBLIC;
CREATE FUNCTION app_any_branch_ok(bs uuid[]) RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT EXISTS (SELECT 1 FROM unnest(bs) AS b WHERE app_branch_ok(b))
$$;
"""

NEW_TABLES = ("branch", "lr_charge", "gate_pass_line", "collection_task", "task_attempt", "reminder", "approval_request")

# Branch confidentiality, enforced by the database on top of the company boundary. Restrictive
# policies are ANDed with the tenant policy, so a request sees only its company AND its branches.
BRANCH_POLICIES = {
    "lr": "app_branch_ok(branch_id) OR app_branch_ok(delivery_branch_id)",
    "trip": "app_branch_ok(branch_id) OR app_any_branch_ok(stop_branch_ids)",
    "money_receipt": "app_branch_ok(branch_id)",
    "collection": "app_branch_ok(branch_id)",
    "cash_handover": "app_branch_ok(branch_id)",
    "bank_deposit": "app_branch_ok(branch_id)",
    "shortage": "app_branch_ok(branch_id)",
    "gate_pass": "app_branch_ok(branch_id)",
    "collection_task": "app_branch_ok(branch_id)",
    "approval_request": "app_branch_ok(branch_id)",
}

GRANTS = {
    "branch": "SELECT, INSERT, UPDATE",
    "lr_charge": "SELECT, INSERT",
    "gate_pass_line": "SELECT, INSERT",
    "collection_task": "SELECT, INSERT",
    "task_attempt": "SELECT, INSERT",
    "reminder": "SELECT, INSERT",
    "approval_request": "SELECT, INSERT",
}
COLUMN_UPDATES = {
    "collection_task": "assigned_to, status, amount_due, oldest_due, next_action_on, last_attempt_at, closed_at",
    "approval_request": "status, decided_by, decided_at, decision_note",
    "gate_pass": "status, delivered_at, pod_received_at, receiver_name, receiver_phone, signature, photo, latitude, "
    "longitude, accuracy_m, pod_recorded_by, void_reason, voided_by, voided_at",
    "app_user": "branch_id, permissions_granted, permissions_revoked",
    "lr_settings": "receipt_prefix, gate_pass_prefix",
    "credit_terms": "reminders",
    "reminder": "status, reason",
    "trip": "stop_branch_ids",
}


def upgrade() -> None:
    op.execute(ROLES)
    op.execute(SCHEMA)
    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
        )
        op.execute(f"GRANT {GRANTS[table]} ON {table} TO {APP_ROLE}")
    for table, rule in BRANCH_POLICIES.items():
        op.execute(f"CREATE POLICY branch_scope ON {table} AS RESTRICTIVE USING ({rule}) WITH CHECK ({rule})")
    for table, columns in COLUMN_UPDATES.items():
        op.execute(f"GRANT UPDATE ({columns}) ON {table} TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION app_branch_ok(uuid), app_any_branch_ok(uuid[]), all_company_ids() TO {APP_ROLE}")


def downgrade() -> None:
    raise NotImplementedError("Branches reshape the gate pass and scope every record; restore from a backup to go back.")
