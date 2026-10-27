"""personal block and allow

Revision ID: d2647abdc3f8
Revises: b1a28ea02dc6
Create Date: 2026-10-27 10:49:17.417129

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2647abdc3f8'
down_revision: Union[str, Sequence[str], None] = 'b1a28ea02dc6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('phone_numbers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('personal_action', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('personal_label', sa.String(length=200), nullable=True))



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('phone_numbers', schema=None) as batch_op:
        batch_op.drop_column('personal_label')
        batch_op.drop_column('personal_action')

