"""Migrations run as the owner role, which owns the tables and is exempt from row-level security.

The API connects as a separate, unprivileged role (FF_DATABASE_URL) that the policies apply to.
"""

import os

from alembic import context
from sqlalchemy import create_engine

engine = create_engine(os.environ["FF_MIGRATION_DATABASE_URL"])
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
