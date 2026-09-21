"""add documents table

The project's first application-owned table: a row per file a researcher
uploaded. Chunks and embeddings stay in the langchain_pg_* tables, which
langchain-postgres creates and owns -- alembic/env.py filters them out of
autogenerate so this migration does not try to manage them.

Revision ID: 7491449276c2
Revises:
Create Date: 2026-09-20 21:52:12.728708

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7491449276c2'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Status values are written out literally rather than imported from
    app.models. A migration is a frozen snapshot of one past schema: importing
    a constant that later gains a value would retroactively change what this
    migration means, and adding a status is its own migration anyway.

    uq_documents_user_id_filename is the load-bearing constraint -- it is what
    makes re-uploading a corrected file replace that document rather than add a
    second copy of it (KNOWN_ISSUES.md -- duplicate chunks on re-ingest).
    """
    op.create_table(
        'documents',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.String(length=255), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('s3_key', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column(
            'status',
            sa.String(length=32),
            server_default='pending',
            nullable=False,
        ),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column(
            'needs_ocr',
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column('chunk_count', sa.Integer(), nullable=True),
        sa.Column('project_id', sa.UUID(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')",
            name=op.f('ck_documents_status'),
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_documents')),
        sa.UniqueConstraint('user_id', 'filename', name=op.f('uq_documents_user_id_filename')),
    )
    op.create_index(
        'ix_documents_user_created', 'documents', ['user_id', 'created_at'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_documents_user_created', table_name='documents')
    op.drop_table('documents')
