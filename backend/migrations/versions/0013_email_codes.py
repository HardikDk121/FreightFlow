"""Email codes that prove a new sign-up owns the address, and status updates on customer notices
(messages are now sent after the payment is saved, then marked sent)."""

import os

from alembic import op

revision = "0013"
down_revision = "0012"

APP_ROLE = os.environ.get("FF_APP_DB_ROLE", "freightflow_app")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE email_code (
            id uuid PRIMARY KEY,
            -- Keyed hash of the address: the table holds no readable emails.
            email_hash text NOT NULL,
            code_hash text NOT NULL,
            attempts integer NOT NULL DEFAULT 0,
            expires_at timestamptz NOT NULL,
            used_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX email_code_email_idx ON email_code (email_hash, created_at DESC);
        """
    )
    # Before sign-up there is no company, so this table, like auth_throttle, has no tenant policy.
    op.execute(f"GRANT SELECT, INSERT ON email_code TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (attempts, used_at) ON email_code TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (status, reason) ON customer_notice TO {APP_ROLE}")
    # Indian mobile numbers are now stored as their 10 digits ("+91 98250 11111" -> "9825011111"),
    # so sign-in by phone and reminders match however the number was first typed.
    ten_digits = r"regexp_replace(regexp_replace({col}, '[\s()\-.]', '', 'g'), '^(\+91|91|0)(?=[6-9][0-9]{{9}}$)', '')"
    for table, col in (("party", "phone"), ("vendor", "phone"), ("branch", "phone"), ("company", "phone"), ("money_receipt", "payer_phone")):
        expr = ten_digits.format(col=col)
        op.execute(f"UPDATE {table} SET {col} = {expr} WHERE {col} IS NOT NULL AND {expr} ~ '^[6-9][0-9]{{9}}$'")
    # app_user.phone is unique: skip a number another user already has in the short form.
    expr = ten_digits.format(col="u.phone")
    op.execute(
        f"UPDATE app_user u SET phone = {expr} WHERE u.phone IS NOT NULL AND {expr} ~ '^[6-9][0-9]{{9}}$' "
        f"AND NOT EXISTS (SELECT 1 FROM app_user o WHERE o.id <> u.id AND o.phone = {expr})"
    )


def downgrade() -> None:
    op.execute("DROP TABLE email_code")
