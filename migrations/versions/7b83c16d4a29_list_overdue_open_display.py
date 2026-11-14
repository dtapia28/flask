"""Allow each list to label overdue open runs as not achieved.

Revision ID: 7b83c16d4a29
Revises: 19c2a724ef10
"""
from alembic import op
import sqlalchemy as sa

revision = '7b83c16d4a29'
down_revision = '19c2a724ef10'
branch_labels = None
depends_on = None


def upgrade():
    columns = {item['name'] for item in sa.inspect(op.get_bind()).get_columns('checklist')}
    if 'overdue_open_as_missed' not in columns:
        op.add_column(
            'checklist',
            sa.Column('overdue_open_as_missed', sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade():
    columns = {item['name'] for item in sa.inspect(op.get_bind()).get_columns('checklist')}
    if 'overdue_open_as_missed' in columns:
        with op.batch_alter_table('checklist') as batch:
            batch.drop_column('overdue_open_as_missed')
