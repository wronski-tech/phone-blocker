"""import run error log

Revision ID: 10deff834a49
Revises: d2647abdc3f8
Create Date: 2026-10-27 10:53:34.247440

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '10deff834a49'
down_revision: Union[str, Sequence[str], None] = 'd2647abdc3f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('import_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('error_log', sa.Text(), nullable=True))



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('import_runs', schema=None) as batch_op:
        batch_op.drop_column('error_log')

