"""Repair application tables missing from a database stamped at an older head.

Revision ID: 8c4fd62b7a10
Revises: f6957a9f2cd9
"""
from alembic import op
import sqlalchemy as sa

revision = '8c4fd62b7a10'
down_revision = 'f6957a9f2cd9'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    present = set(sa.inspect(bind).get_table_names())

    def create_if_missing(name, *args, **kwargs):
        if name not in present:
            op.create_table(name, *args, **kwargs)
            present.add(name)

    # Create in foreign-key dependency order. This also repairs databases where
    # an earlier migration version was recorded but its DDL was later lost.
    create_if_missing(
        'change_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('record_id', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.Integer()),
        sa.Column('changed_at', sa.DateTime()),
        sa.Column('reason', sa.Text()),
        sa.Column('previous', sa.Text()),
    )
    create_if_missing(
        'checklist',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('active', sa.Boolean()),
    )
    create_if_missing(
        'mail_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('key', sa.String(length=255), unique=True),
        sa.Column('recipient', sa.String(length=255)),
        sa.Column('kind', sa.String(length=30)),
        sa.Column('sent_at', sa.DateTime()),
        sa.Column('body', sa.Text()),
        sa.Column('status', sa.String(length=20), server_default='pending'),
        sa.Column('attempts', sa.Integer(), server_default='1'),
        sa.Column('error', sa.String(length=80)),
    )
    create_if_missing(
        'user',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('email', sa.String(length=255), nullable=False, unique=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('password', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
    )
    create_if_missing(
        'assignment',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('checklist_id', sa.Integer(), sa.ForeignKey('checklist.id'), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('weekdays', sa.String(length=20)),
        sa.Column('close_time', sa.Time()),
        sa.Column('paused', sa.Boolean()),
        sa.Column('alert_admin', sa.Boolean()),
        sa.Column('alert_from', sa.Date()),
    )
    create_if_missing(
        'task',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('checklist_id', sa.Integer(), sa.ForeignKey('checklist.id'), nullable=False),
        sa.Column('text', sa.String(length=300), nullable=False),
        sa.Column('position', sa.Integer()),
        sa.Column('active', sa.Boolean()),
    )
    create_if_missing(
        'token',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('digest', sa.String(length=64), unique=True),
        sa.Column('purpose', sa.String(length=20)),
        sa.Column('expires', sa.DateTime(), nullable=False),
        sa.Column('used', sa.Boolean()),
    )
    create_if_missing(
        'daily_record',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('assignment_id', sa.Integer(), sa.ForeignKey('assignment.id'), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20)),
        sa.Column('closed_at', sa.DateTime()),
        sa.UniqueConstraint('assignment_id', 'day'),
    )
    create_if_missing(
        'task_snapshot',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('record_id', sa.Integer(), sa.ForeignKey('daily_record.id'), nullable=False),
        sa.Column('task_id', sa.Integer()),
        sa.Column('text', sa.String(length=300), nullable=False),
        sa.Column('done', sa.Boolean()),
    )

    # If mail_log survived but predates the delivery-state columns, add only
    # those missing columns. Existing rows and delivery history are preserved.
    mail_columns = {column['name'] for column in sa.inspect(bind).get_columns('mail_log')}
    additions = (
        ('status', sa.String(length=20), 'pending'),
        ('attempts', sa.Integer(), '1'),
        ('error', sa.String(length=80), None),
    )
    for name, column_type, default in additions:
        if name not in mail_columns:
            column = sa.Column(name, column_type, server_default=default) if default is not None else sa.Column(name, column_type)
            op.add_column('mail_log', column)


def downgrade():
    # This revision restores the schema promised by its parent revision. It
    # introduces no new application schema, so downgrade keeps restored tables
    # and data intact while Alembic moves its version marker back.
    pass
