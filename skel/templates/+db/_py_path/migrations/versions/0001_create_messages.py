'''create messages

Revision ID: 0001
Revises:
'''

from alembic import op
import sqlalchemy as sa


revision      = '0001'
down_revision = None
branch_labels = None
depends_on    = None


def upgrade():
    op.create_table('messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('text', sa.String(), nullable=False),
        sa.Column('created', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('messages')
