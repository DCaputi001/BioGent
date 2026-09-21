"""add questions table

A researcher's question history: each answered question, its answer, and the
filenames it was grounded in. Owner-scoped by user_id, like documents.

sources is a snapshot of filenames, not a foreign key to documents, so deleting
a document never rewrites or breaks a past answer.

Revision ID: 1d2e65e6ab18
Revises: 7491449276c2
Create Date: 2026-09-21 19:33:52.276087

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1d2e65e6ab18'
down_revision: str | Sequence[str] | None = '7491449276c2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'questions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.String(length=255), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column(
            'sources',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]',
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_questions')),
    )
    op.create_index(
        'ix_questions_user_created', 'questions', ['user_id', 'created_at'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_questions_user_created', table_name='questions')
    op.drop_table('questions')
