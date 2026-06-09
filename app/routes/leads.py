"""Rotas para gerenciamento de leads (PostgreSQL / asyncpg)."""
import logging
import re
import uuid
from typing import Optional
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.config import settings
from app.database import get_pool
from app.rate_limit import limiter
from app.security import require_admin_key
from app.services.email_service import send_lead_notification

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/leads", tags=["leads"])

_LEAD_COLUMNS = (
    "id, created_at, nome, contato, empresa, contato_feito, elevenlabs_conversation_id"
)


def _serialize_lead(row) -> dict:
    """Converte uma Record do asyncpg no formato esperado pela API."""
    return {
        "id": str(row["id"]),
        "timestamp": row["created_at"].isoformat() if row["created_at"] else "",
        "nome": row["nome"],
        "contato": row["contato"],
        "empresa": row["empresa"],
        "contato_feito": bool(row["contato_feito"]),
        "elevenlabs_conversation_id": row["elevenlabs_conversation_id"],
    }


class LeadCreate(BaseModel):
    nome: str
    contato: str
    empresa: Optional[str] = None
    contato_feito: Optional[bool] = None
    elevenlabs_conversation_id: Optional[str] = None

    @field_validator("contato")
    @classmethod
    def strip_leading_plus(cls, v: str) -> str:
        return re.sub(r"^\+", "", v)


@router.post("/register")
@limiter.limit("20/minute")
async def register_lead(request: Request, lead: LeadCreate):
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL não configurado.")
    try:
        pool = get_pool()
        # Insert atômico: a constraint UNIQUE(contato) resolve a corrida do dedup.
        # `xmax = 0` distingue um insert novo de um conflito (linha já existente).
        row = await pool.fetchrow(
            """insert into leads (nome, contato, empresa, contato_feito, elevenlabs_conversation_id)
               values ($1, $2, $3, coalesce($4, false), $5)
               on conflict (contato) do update set contato = leads.contato
               returning id, (xmax = 0) as inserted""",
            lead.nome,
            lead.contato,
            lead.empresa,
            lead.contato_feito,
            lead.elevenlabs_conversation_id,
        )
        inserted = row["inserted"]
        # No fluxo normal o convid não chega aqui (entra depois via PATCH, quando a
        # conversa inicia). Mas se uma integração já criar o lead com convid, notifica.
        if inserted and lead.elevenlabs_conversation_id:
            await send_lead_notification(
                {
                    "nome": lead.nome,
                    "contato": lead.contato,
                    "elevenlabs_conversation_id": lead.elevenlabs_conversation_id,
                }
            )
        return {
            "success": True,
            "message": (
                "Lead registrado com sucesso"
                if inserted
                else "Lead já registrado (contato já existe)"
            ),
            "lead_id": str(row["id"]),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Erro inesperado em rota de leads")
        raise HTTPException(status_code=500, detail="Erro ao registrar lead.")


@router.get("/list", dependencies=[Depends(require_admin_key)])
async def list_leads():
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL não configurado.")
    try:
        pool = get_pool()
        rows = await pool.fetch(
            f"select {_LEAD_COLUMNS} from leads order by created_at desc"
        )
        return {"leads": [_serialize_lead(r) for r in rows]}
    except Exception:
        logger.exception("Erro inesperado em rota de leads")
        raise HTTPException(status_code=500, detail="Erro ao listar leads.")


@router.get("/by-contato", dependencies=[Depends(require_admin_key)])
async def get_lead_by_contato(contato: str):
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL não configurado.")
    try:
        pool = get_pool()
        row = await pool.fetchrow(
            f"select {_LEAD_COLUMNS} from leads where contato = $1", contato
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Lead não encontrado.")
        return _serialize_lead(row)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Erro inesperado em rota de leads")
        raise HTTPException(status_code=500, detail="Erro ao buscar lead.")


class ContatoFeitoUpdate(BaseModel):
    contato_feito: bool


class EmpresaUpdate(BaseModel):
    empresa: str


@router.patch("/{lead_id}/empresa", dependencies=[Depends(require_admin_key)])
async def update_empresa(lead_id: str, body: EmpresaUpdate):
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL não configurado.")
    try:
        lead_uuid = uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de lead inválido.")
    try:
        pool = get_pool()
        row = await pool.fetchrow(
            "update leads set empresa = $1 where id = $2 returning id",
            body.empresa,
            lead_uuid,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Lead não encontrado.")
        return {"success": True, "empresa": body.empresa}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Erro inesperado em rota de leads")
        raise HTTPException(status_code=500, detail="Erro ao atualizar lead.")


@router.patch("/{lead_id}/contato-feito", dependencies=[Depends(require_admin_key)])
async def update_contato_feito(lead_id: str, body: ContatoFeitoUpdate):
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL não configurado.")
    try:
        lead_uuid = uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de lead inválido.")
    try:
        pool = get_pool()
        row = await pool.fetchrow(
            "update leads set contato_feito = $1 where id = $2 returning id",
            body.contato_feito,
            lead_uuid,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Lead não encontrado.")
        return {"success": True, "contato_feito": body.contato_feito}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Erro inesperado em rota de leads")
        raise HTTPException(status_code=500, detail="Erro ao atualizar lead.")


# ---------------------------------------------------------------------------
# CRUD REST completo (operam sobre o lead pelo seu UUID)
# ---------------------------------------------------------------------------


class LeadReplace(BaseModel):
    """Corpo do PUT — substituição completa do lead (todos os campos)."""

    nome: str
    contato: str
    empresa: Optional[str] = None
    contato_feito: bool = False
    elevenlabs_conversation_id: Optional[str] = None

    @field_validator("contato")
    @classmethod
    def strip_leading_plus(cls, v: str) -> str:
        return re.sub(r"^\+", "", v)


class LeadPatch(BaseModel):
    """Corpo do PATCH — atualização parcial (apenas os campos enviados)."""

    nome: Optional[str] = None
    contato: Optional[str] = None
    empresa: Optional[str] = None
    contato_feito: Optional[bool] = None
    elevenlabs_conversation_id: Optional[str] = None

    @field_validator("contato")
    @classmethod
    def strip_leading_plus(cls, v: Optional[str]) -> Optional[str]:
        return re.sub(r"^\+", "", v) if v is not None else v


def _parse_lead_id(lead_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de lead inválido.")


@router.post("", dependencies=[Depends(require_admin_key)], status_code=201)
async def create_lead(lead: LeadCreate):
    """Cria um lead e retorna o registro completo. Falha (409) se o contato já existir."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL não configurado.")
    try:
        pool = get_pool()
        row = await pool.fetchrow(
            f"""insert into leads (nome, contato, empresa, contato_feito, elevenlabs_conversation_id)
                values ($1, $2, $3, coalesce($4, false), $5)
                returning {_LEAD_COLUMNS}""",
            lead.nome,
            lead.contato,
            lead.empresa,
            lead.contato_feito,
            lead.elevenlabs_conversation_id,
        )
        return _serialize_lead(row)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="Já existe um lead com este contato.")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Erro inesperado em rota de leads")
        raise HTTPException(status_code=500, detail="Erro ao criar lead.")


@router.get("/{lead_id}", dependencies=[Depends(require_admin_key)])
async def get_lead(lead_id: str):
    """Busca um lead pelo seu UUID."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL não configurado.")
    lead_uuid = _parse_lead_id(lead_id)
    try:
        pool = get_pool()
        row = await pool.fetchrow(
            f"select {_LEAD_COLUMNS} from leads where id = $1", lead_uuid
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Lead não encontrado.")
        return _serialize_lead(row)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Erro inesperado em rota de leads")
        raise HTTPException(status_code=500, detail="Erro ao buscar lead.")


@router.put("/{lead_id}", dependencies=[Depends(require_admin_key)])
async def replace_lead(lead_id: str, lead: LeadReplace):
    """Substituição completa de um lead (todos os campos são sobrescritos)."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL não configurado.")
    lead_uuid = _parse_lead_id(lead_id)
    try:
        pool = get_pool()
        row = await pool.fetchrow(
            f"""update leads
                set nome = $1,
                    contato = $2,
                    empresa = $3,
                    contato_feito = $4,
                    elevenlabs_conversation_id = $5
                where id = $6
                returning {_LEAD_COLUMNS}""",
            lead.nome,
            lead.contato,
            lead.empresa,
            lead.contato_feito,
            lead.elevenlabs_conversation_id,
            lead_uuid,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Lead não encontrado.")
        return _serialize_lead(row)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="Já existe um lead com este contato.")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Erro inesperado em rota de leads")
        raise HTTPException(status_code=500, detail="Erro ao atualizar lead.")


@router.patch("/{lead_id}", dependencies=[Depends(require_admin_key)])
async def patch_lead(lead_id: str, lead: LeadPatch):
    """Atualização parcial: grava apenas os campos presentes no corpo da requisição."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL não configurado.")
    lead_uuid = _parse_lead_id(lead_id)

    # Monta o SET dinamicamente apenas com os campos enviados (exclude_unset).
    changes = lead.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar.")

    set_clauses = []
    values = []
    for idx, (column, value) in enumerate(changes.items(), start=1):
        set_clauses.append(f"{column} = ${idx}")
        values.append(value)
    values.append(lead_uuid)  # placeholder do WHERE

    query = (
        f"update leads set {', '.join(set_clauses)} "
        f"where id = ${len(values)} returning {_LEAD_COLUMNS}"
    )
    # Início de conversa = momento em que o front anexa o elevenlabs_conversation_id
    # ao lead via PATCH. Só notifica se o convid mudou (evita e-mail duplicado se o
    # mesmo id for reenviado), comparando com o valor atual antes do update.
    new_convid = changes.get("elevenlabs_conversation_id")
    try:
        pool = get_pool()
        prev_convid = None
        if new_convid:
            prev_convid = await pool.fetchval(
                "select elevenlabs_conversation_id from leads where id = $1", lead_uuid
            )
        row = await pool.fetchrow(query, *values)
        if row is None:
            raise HTTPException(status_code=404, detail="Lead não encontrado.")
        if new_convid and new_convid != prev_convid:
            await send_lead_notification(
                {
                    "nome": row["nome"],
                    "contato": row["contato"],
                    "elevenlabs_conversation_id": row["elevenlabs_conversation_id"],
                }
            )
        return _serialize_lead(row)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="Já existe um lead com este contato.")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Erro inesperado em rota de leads")
        raise HTTPException(status_code=500, detail="Erro ao atualizar lead.")


@router.delete("/{lead_id}", dependencies=[Depends(require_admin_key)])
async def delete_lead(lead_id: str):
    """Remove um lead pelo seu UUID."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL não configurado.")
    lead_uuid = _parse_lead_id(lead_id)
    try:
        pool = get_pool()
        row = await pool.fetchrow(
            "delete from leads where id = $1 returning id", lead_uuid
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Lead não encontrado.")
        return {"success": True, "deleted_id": str(row["id"])}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Erro inesperado em rota de leads")
        raise HTTPException(status_code=500, detail="Erro ao deletar lead.")
