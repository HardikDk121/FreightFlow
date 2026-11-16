"""E-way bill fields on the LR, and registration papers on the truck."""

from alembic import op

revision = "0005"
down_revision = "0004"

UPGRADE = """
ALTER TABLE lr
    ADD COLUMN from_state text,
    ADD COLUMN to_state text,
    ADD COLUMN goods_category text NOT NULL DEFAULT 'regular'
        CHECK (goods_category IN ('regular', 'job_work', 'handicraft', 'household_effects', 'exempt_goods')),
    ADD COLUMN trip_leg text NOT NULL DEFAULT 'direct'
        CHECK (trip_leg IN ('direct', 'consignor_to_hub', 'hub_to_consignee')),
    ADD COLUMN distance_km integer CHECK (distance_km > 0),
    ADD COLUMN hsn_code text CHECK (hsn_code ~ '^[0-9]{4}([0-9]{2}){0,2}$'),
    ADD COLUMN consignor_pan text CHECK (consignor_pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'),
    ADD COLUMN consignee_pan text CHECK (consignee_pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'),
    ADD COLUMN enrolment_id text CHECK (enrolment_id ~ '^[0-9A-Z]{15}$'),
    -- LRs saved before this migration were never assessed.
    ADD COLUMN ewb_status text NOT NULL DEFAULT 'not_assessed'
        CHECK (ewb_status IN ('not_assessed', 'not_required', 'exempt', 'pending', 'awaiting_part_b', 'active')),
    ADD COLUMN ewb_responsible text CHECK (ewb_responsible IN ('consignor', 'consignee', 'transporter')),
    ADD COLUMN ewb_part_b_required boolean NOT NULL DEFAULT false,
    ADD COLUMN ewb_reason text,
    ADD COLUMN ewb_vehicle_number text,
    ADD COLUMN ewb_valid_until timestamptz;
CREATE INDEX lr_ewb_expiry_idx ON lr (company_id, ewb_valid_until) WHERE ewb_status = 'active';

ALTER TABLE truck
    ADD COLUMN model_year integer CHECK (model_year BETWEEN 1990 AND 2100),
    ADD COLUMN insurance_expiry date,
    ADD COLUMN fitness_expiry date;
"""

DOWNGRADE = """
ALTER TABLE truck DROP COLUMN model_year, DROP COLUMN insurance_expiry, DROP COLUMN fitness_expiry;
ALTER TABLE lr
    DROP COLUMN from_state, DROP COLUMN to_state, DROP COLUMN goods_category, DROP COLUMN trip_leg,
    DROP COLUMN distance_km, DROP COLUMN hsn_code, DROP COLUMN consignor_pan, DROP COLUMN consignee_pan,
    DROP COLUMN enrolment_id, DROP COLUMN ewb_status, DROP COLUMN ewb_responsible,
    DROP COLUMN ewb_part_b_required, DROP COLUMN ewb_reason, DROP COLUMN ewb_vehicle_number,
    DROP COLUMN ewb_valid_until;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
