"""prefix rules

Revision ID: 81f27febef4d
Revises: 285c21b2f847
Create Date: 2026-10-27 11:55:28.116687

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '81f27febef4d'
down_revision: Union[str, Sequence[str], None] = '285c21b2f847'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('rules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('prefix', sa.String(length=15), nullable=False),
    sa.Column('action', sa.String(length=10), nullable=False),
    sa.Column('note', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rules')),
    sa.UniqueConstraint('prefix', name=op.f('uq_rules_prefix'))
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('rules')
