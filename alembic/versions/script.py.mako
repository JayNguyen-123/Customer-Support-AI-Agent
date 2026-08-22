"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision}
Create Date: ${create_date}
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
${imports}

# Revision identifiers, used chronologically by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """Executes database schema evolution steps during an upgrade."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Reverses table modifications, returning structure back to previous version."""
    ${downgrades if downgrades else "pass"}
