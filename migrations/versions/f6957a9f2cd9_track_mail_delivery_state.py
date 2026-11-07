"""track mail delivery state

Revision ID: f6957a9f2cd9
Revises: fc94198ac60a
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6957a9f2cd9'
down_revision = 'fc94198ac60a'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('mail_log') as batch:
        batch.add_column(sa.Column('status', sa.String(length=20), nullable=True, server_default='pending'))
        batch.add_column(sa.Column('attempts', sa.Integer(), nullable=True, server_default='1'))
        batch.add_column(sa.Column('error', sa.String(length=80), nullable=True))

def downgrade():
    with op.batch_alter_table('mail_log') as batch:
        batch.drop_column('error')
        batch.drop_column('attempts')
        batch.drop_column('status')
