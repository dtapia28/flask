"""Repair databases stamped at da2 without their application tables.

Revision ID: e1b9365a70c4
Revises: da2c87f179ab
"""
from alembic import op
import sqlalchemy as sa
from migrations.schema_repair import ensure_base_schema

revision = 'e1b9365a70c4'
down_revision = 'da2c87f179ab'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # A prior SQLite DDL failure can leave Alembic at da2 while the tables are
    # absent. This new forward revision guarantees a pending repair step.
    ensure_base_schema(bind)
    inspector = sa.inspect(bind)
    for table in ('task', 'task_snapshot'):
        columns = {column['name'] for column in inspector.get_columns(table)}
        if 'section' not in columns:
            op.add_column(table, sa.Column('section', sa.String(length=160), nullable=False, server_default='General'))
            inspector = sa.inspect(bind)


def downgrade():
    # Restores the schema already expected at da2, so keep restored tables.
    pass
