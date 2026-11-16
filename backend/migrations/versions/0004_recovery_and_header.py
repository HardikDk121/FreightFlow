"""Password reset codes, request throttling, and the company details printed on the LR header."""

import os

from alembic import op

revision = "0004"
down_revision = "0003"

APP_ROLE = os.environ.get("FF_APP_DB_ROLE", "freightflow_app")

SCHEMA = """
ALTER TABLE company ADD COLUMN tagline text, ADD COLUMN phone text;

CREATE TABLE password_reset (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES company (id),
    user_id uuid NOT NULL REFERENCES app_user (id),
    code_hash text NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX password_reset_user_idx ON password_reset (user_id, created_at DESC);

-- One row per recovery request, keyed by a hash of the email, phone or IP it came for.
-- It holds no company data, so it is not tenant-scoped.
CREATE TABLE auth_throttle (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auth_throttle_key_idx ON auth_throttle (key_hash, created_at DESC);
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute("ALTER TABLE password_reset ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON password_reset "
        "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON password_reset TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON auth_throttle TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP TABLE auth_throttle")
    op.execute("DROP TABLE password_reset")
    op.execute("ALTER TABLE company DROP COLUMN tagline, DROP COLUMN phone")
