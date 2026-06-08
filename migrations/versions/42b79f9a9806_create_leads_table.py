"""create leads table

Revision ID: 42b79f9a9806
Revises:
Create Date: 2026-06-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "42b79f9a9806"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Cria a tabela leads (espelha o schema do Supabase, com melhorias)."""
    op.execute(
        """
        create table leads (
            id                          uuid primary key default gen_random_uuid(),
            created_at                  timestamptz not null default now(),
            nome                        text not null,
            contato                     text not null unique,
            empresa                     text,
            contato_feito               boolean not null default false,
            elevenlabs_conversation_id  text
        )
        """
    )
    # `contato unique` (acima) resolve o dedup atômico E já cria um índice
    # implícito em `contato`, que acelera o GET /api/leads/by-contato.
    # Por isso NÃO criamos um idx_leads_contato separado (seria redundante).


def downgrade() -> None:
    """Remove a tabela leads."""
    op.drop_table("leads")
