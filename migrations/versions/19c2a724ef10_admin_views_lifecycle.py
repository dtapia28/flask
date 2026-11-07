"""Add lifecycle markers for users, lists, and assignments.

Revision ID: 19c2a724ef10
Revises: ac41d202fbaa
"""
from alembic import op
import sqlalchemy as sa

revision = '19c2a724ef10'
down_revision = 'ac41d202fbaa'
branch_labels = None
depends_on = None


def upgrade():
    for table, column, type_ in (
        ('user', 'deleted_at', sa.DateTime()),
        ('checklist', 'archived_at', sa.DateTime()),
        ('assignment', 'ended_at', sa.DateTime()),
    ):
        columns = {item['name'] for item in sa.inspect(op.get_bind()).get_columns(table)}
        if column not in columns:
            op.add_column(table, sa.Column(column, type_, nullable=True))
    if 'assignment_schedule' not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table('assignment_schedule',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('assignment_id', sa.Integer(), sa.ForeignKey('assignment.id'), nullable=False),
            sa.Column('effective_from', sa.Date(), nullable=False),
            sa.Column('weekdays', sa.String(length=20), nullable=False),
            sa.Column('close_time', sa.Time(), nullable=False),
            sa.Column('alert_admin', sa.Boolean(), nullable=False, server_default=sa.false()))
    schedule_columns = {item['name'] for item in sa.inspect(op.get_bind()).get_columns('assignment_schedule')}
    if 'paused' not in schedule_columns:
        op.add_column('assignment_schedule', sa.Column('paused', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    if 'assignment_schedule' in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table('assignment_schedule')
    for table, column in (('assignment', 'ended_at'), ('checklist', 'archived_at'), ('user', 'deleted_at')):
        columns = {item['name'] for item in sa.inspect(op.get_bind()).get_columns(table)}
        if column in columns:
            with op.batch_alter_table(table) as batch:
                batch.drop_column(column)
