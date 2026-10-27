"""source states

Revision ID: 285c21b2f847
Revises: 10deff834a49
Create Date: 2026-10-27 11:26:10.596496

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '285c21b2f847'
down_revision: Union[str, Sequence[str], None] = '10deff834a49'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('source_states',
    sa.Column('source', sa.String(length=50), nullable=False),
    sa.Column('state', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('source', name=op.f('pk_source_states'))
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('source_states')
