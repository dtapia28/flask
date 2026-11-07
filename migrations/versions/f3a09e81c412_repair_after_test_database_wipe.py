"""Restore application tables if a test run left only Alembic's version marker.

Revision ID: f3a09e81c412
Revises: e1b9365a70c4
"""
from alembic import op
import sqlalchemy as sa
from migrations.schema_repair import ensure_base_schema

revision = 'f3a09e81c412'
down_revision = 'e1b9365a70c4'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    ensure_base_schema(bind)
    inspector = sa.inspect(bind)
    for table in ('task', 'task_snapshot'):
        columns = {column['name'] for column in inspector.get_columns(table)}
        if 'section' not in columns:
            op.add_column(table, sa.Column('section', sa.String(length=160), nullable=False, server_default='General'))
            inspector = sa.inspect(bind)


def downgrade():
    # Reconciles the schema promised by e1b9365a70c4 without removing data.
    pass
