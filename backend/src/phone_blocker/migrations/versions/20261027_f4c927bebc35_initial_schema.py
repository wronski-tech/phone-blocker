"""initial schema

Revision ID: f4c927bebc35
Revises: 
Create Date: 2026-10-27 10:09:11.737831

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4c927bebc35'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('organizations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=500), nullable=False),
    sa.Column('street', sa.String(length=300), nullable=True),
    sa.Column('postal_code', sa.String(length=10), nullable=True),
    sa.Column('city', sa.String(length=200), nullable=True),
    sa.Column('commune', sa.String(length=200), nullable=True),
    sa.Column('county', sa.String(length=200), nullable=True),
    sa.Column('voivodeship', sa.String(length=100), nullable=True),
    sa.Column('website', sa.String(length=500), nullable=True),
    sa.Column('email', sa.String(length=300), nullable=True),
    sa.Column('nip', sa.String(length=20), nullable=True),
    sa.Column('regon', sa.String(length=20), nullable=True),
    sa.Column('search_text', sa.Text(), nullable=False),
    sa.Column('source', sa.String(length=50), nullable=False),
    sa.Column('source_url', sa.String(length=1000), nullable=False),
    sa.Column('fetched_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_organizations')),
    sa.UniqueConstraint('source_url', name=op.f('uq_organizations_source_url'))
    )
    op.create_index(op.f('ix_organizations_fetched_at'), 'organizations', ['fetched_at'], unique=False)

    op.create_table('phone_numbers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('number', sa.BigInteger(), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=True),
    sa.Column('blocked', sa.Boolean(), nullable=False),
    sa.Column('version', sa.BigInteger(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_phone_numbers')),
    sa.UniqueConstraint('number', name=op.f('uq_phone_numbers_number'))
    )
    op.create_index(op.f('ix_phone_numbers_version'), 'phone_numbers', ['version'], unique=False)

    op.create_table('sync_state',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sync_state'))
    )
    op.execute("INSERT INTO sync_state (id, version) VALUES (1, 0)")
    op.create_table('listings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('phone_number_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('department', sa.String(length=200), nullable=True),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_listings_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['phone_number_id'], ['phone_numbers.id'], name=op.f('fk_listings_phone_number_id_phone_numbers')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_listings')),
    sa.UniqueConstraint('organization_id', 'phone_number_id', 'kind', 'department', name=op.f('uq_listings_organization_id_phone_number_id_kind_department'))
    )
    op.create_index(op.f('ix_listings_organization_id'), 'listings', ['organization_id'], unique=False)
    op.create_index(op.f('ix_listings_phone_number_id'), 'listings', ['phone_number_id'], unique=False)

    op.create_table('reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('phone_number_id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['phone_number_id'], ['phone_numbers.id'], name=op.f('fk_reports_phone_number_id_phone_numbers')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reports'))
    )
    op.create_index(op.f('ix_reports_phone_number_id'), 'reports', ['phone_number_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_reports_phone_number_id'), table_name='reports')
    op.drop_table('reports')
    op.drop_index(op.f('ix_listings_phone_number_id'), table_name='listings')
    op.drop_index(op.f('ix_listings_organization_id'), table_name='listings')
    op.drop_table('listings')
    op.drop_table('sync_state')
    op.drop_index(op.f('ix_phone_numbers_version'), table_name='phone_numbers')
    op.drop_table('phone_numbers')
    op.drop_index(op.f('ix_organizations_fetched_at'), table_name='organizations')
    op.drop_table('organizations')
