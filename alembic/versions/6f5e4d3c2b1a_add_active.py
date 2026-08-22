"""add_active

Revision ID: 6f5e4d3c2b1a
Revises: 1a2b3c4d5e6f
Create Date: 2026-08-20 17:38:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# Revision identifiers, used chronologically by Alembic.
revision: str = '6f5e4d3c2b1a'
down_revision: Union[str, None] = '1a2b3c4d5e6f'  # Points directly to the first migration
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Safely adds the status tracking column to the existing table matrix."""
    # Using a batch block ensures compatibility with engines like SQLite or Postgres
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'is_active',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('1') # Enforces active state default on existing rows
            )
        )


def downgrade() -> None:
    """Removes modifications, returning table structure back to version 1."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('is_active')
