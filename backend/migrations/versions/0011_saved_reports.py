"""Saved and scheduled analytics reports."""

import os

from alembic import op

revision = "0011"
down_revision = "0010"

APP_ROLE = os.environ.get("FF_APP_DB_ROLE", "freightflow_app")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE saved_report (
            id uuid PRIMARY KEY,
            company_id uuid NOT NULL REFERENCES company (id),
            name text NOT NULL,
            analysis text NOT NULL,
            -- Filters with a named period ("last_month"), so a scheduled report always covers the right dates.
            filters jsonb NOT NULL,
            custom jsonb,
            schedule text NOT NULL DEFAULT 'none' CHECK (schedule IN ('none', 'daily', 'weekly', 'monthly')),
            recipients text[] NOT NULL DEFAULT '{}',
            is_active boolean NOT NULL DEFAULT true,
            created_by uuid NOT NULL REFERENCES app_user (id),
            last_sent_on date,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT saved_report_recipients CHECK (schedule = 'none' OR cardinality(recipients) > 0)
        );
        CREATE UNIQUE INDEX saved_report_name_uq ON saved_report (company_id, lower(name));
        """
    )
    op.execute("ALTER TABLE saved_report ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON saved_report "
        "USING (company_id = app_company_id()) WITH CHECK (company_id = app_company_id())"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON saved_report TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP TABLE saved_report")
