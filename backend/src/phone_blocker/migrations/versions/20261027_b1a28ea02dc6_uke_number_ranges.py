"""uke number ranges

Revision ID: b1a28ea02dc6
Revises: c9146be23607
Create Date: 2026-10-27 10:47:00.668232

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1a28ea02dc6'
down_revision: Union[str, Sequence[str], None] = 'c9146be23607'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('number_ranges',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('prefix', sa.String(length=15), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('operator', sa.String(length=300), nullable=False),
    sa.Column('operator_id', sa.Integer(), nullable=False),
    sa.Column('zone', sa.String(length=100), nullable=True),
    sa.Column('service', sa.String(length=300), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_number_ranges')),
    sa.UniqueConstraint('prefix', name=op.f('uq_number_ranges_prefix'))
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('number_ranges')
