"""multiple sources and import runs

Renames organizations.source_url to source_id (unique per source) and adds import_runs.

Revision ID: c9146be23607
Revises: f4c927bebc35
Create Date: 2026-10-27 10:22:56.687570

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9146be23607'
down_revision: Union[str, Sequence[str], None] = 'f4c927bebc35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('import_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=50), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('saved', sa.Integer(), nullable=False),
    sa.Column('removed', sa.Integer(), nullable=False),
    sa.Column('errors', sa.Integer(), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_runs'))
    )
    op.create_index(op.f('ix_import_runs_source'), 'import_runs', ['source'], unique=False)

    # Batch mode so SQLite can do it too; a rename keeps existing BIP rows. The new
    # constraint needs its own batch: within one, SQLite silently drops a constraint on a
    # column renamed in the same batch.
    with op.batch_alter_table('organizations') as batch_op:
        batch_op.drop_constraint('uq_organizations_source_url', type_='unique')
        batch_op.alter_column('source_url', new_column_name='source_id',
                              existing_type=sa.String(length=1000), existing_nullable=False)
    with op.batch_alter_table('organizations') as batch_op:
        batch_op.create_unique_constraint('uq_organizations_source_source_id', ['source', 'source_id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('organizations') as batch_op:
        batch_op.drop_constraint('uq_organizations_source_source_id', type_='unique')
        batch_op.alter_column('source_id', new_column_name='source_url',
                              existing_type=sa.String(length=1000), existing_nullable=False)
    with op.batch_alter_table('organizations') as batch_op:
        batch_op.create_unique_constraint('uq_organizations_source_url', ['source_url'])

    op.drop_index(op.f('ix_import_runs_source'), table_name='import_runs')
    op.drop_table('import_runs')
