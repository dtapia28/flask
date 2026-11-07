"""Reconcile a SQLite database whose failed DDL revision was stamped applied.

Revision ID: da2c87f179ab
Revises: ba74c618f091
"""
from alembic import op
import sqlalchemy as sa
from migrations.schema_repair import ensure_base_schema

revision = 'da2c87f179ab'
down_revision = 'ba74c618f091'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # SQLite may retain the Alembic version marker after a failed, non-atomic
    # DDL upgrade. Recreate only absent base tables before adding section data.
    ensure_base_schema(bind)
    inspector = sa.inspect(bind)
    for table in ('task', 'task_snapshot'):
        columns = {column['name'] for column in inspector.get_columns(table)}
        if 'section' not in columns:
            op.add_column(table, sa.Column('section', sa.String(length=160), nullable=False, server_default='General'))
            inspector = sa.inspect(bind)


def downgrade():
    # Reconciliation only restores the schema already promised by ba74c618f091.
    pass
