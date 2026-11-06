"""Add named sections to checklist tasks and daily snapshots.

Revision ID: ba74c618f091
Revises: 8c4fd62b7a10
"""
from alembic import op
import sqlalchemy as sa

revision = 'ba74c618f091'
down_revision = '8c4fd62b7a10'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ('task', 'task_snapshot'):
        columns = {column['name'] for column in inspector.get_columns(table)}
        if 'section' not in columns:
            op.add_column(table, sa.Column('section', sa.String(length=160), nullable=False, server_default='General'))
            inspector = sa.inspect(bind)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ('task_snapshot', 'task'):
        columns = {column['name'] for column in inspector.get_columns(table)}
        if 'section' in columns:
            with op.batch_alter_table(table) as batch:
                batch.drop_column('section')
            inspector = sa.inspect(bind)
