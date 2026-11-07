"""track whether an account has configured its password

Revision ID: ac41d202fbaa
Revises: f3a09e81c412
"""
from alembic import op
import sqlalchemy as sa

revision = 'ac41d202fbaa'
down_revision = 'f3a09e81c412'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user',
        sa.Column('password_configured', sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    users = sa.table(
        'user',
        sa.column('id', sa.Integer()),
        sa.column('role', sa.String()),
        sa.column('password_configured', sa.Boolean()),
    )
    tokens = sa.table(
        'token',
        sa.column('user_id', sa.Integer()),
        sa.column('purpose', sa.String()),
        sa.column('used', sa.Boolean()),
    )
    previously_configured = sa.select(tokens.c.user_id).where(
        tokens.c.used.is_(True),
        tokens.c.purpose.in_(('setup', 'reset')),
    )
    pending_setup = sa.select(tokens.c.user_id).where(
        tokens.c.purpose == 'setup',
        tokens.c.used.is_(False),
    )
    op.get_bind().execute(
        users.update()
        .where(
            sa.or_(
                users.c.role == 'admin',
                sa.and_(
                    users.c.id.in_(previously_configured),
                    ~users.c.id.in_(pending_setup),
                ),
            )
        )
        .values(password_configured=sa.true())
    )


def downgrade():
    op.drop_column('user', 'password_configured')
