"""Non-destructive helpers for restoring tables expected by the app schema."""
import sqlalchemy as sa
from alembic import op


def ensure_base_schema(bind=None):
    bind = bind or op.get_bind()
    present = set(sa.inspect(bind).get_table_names())

    def create_if_missing(name, *args, **kwargs):
        if name not in present:
            op.create_table(name, *args, **kwargs)
            present.add(name)

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

    mail_columns = {column['name'] for column in sa.inspect(bind).get_columns('mail_log')}
    for name, column_type, default in (
        ('status', sa.String(length=20), 'pending'),
        ('attempts', sa.Integer(), '1'),
        ('error', sa.String(length=80), None),
    ):
        if name not in mail_columns:
            column = sa.Column(name, column_type, server_default=default) if default is not None else sa.Column(name, column_type)
            op.add_column('mail_log', column)
