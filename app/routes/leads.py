"""Rotas para gerenciamento de leads (PostgreSQL/Supabase)."""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.database import get_pool
from app.security import require_admin_key

router = APIRouter(prefix="/api/leads", tags=["leads"])


class LeadCreate(BaseModel):
    nome: str
    email: str
    telefone: str
    empresa: str


@router.post("/register")
async def register_lead(lead: LeadCreate):
    """Registra um novo lead no PostgreSQL (Supabase). Só retorna sucesso após confirmar que foi salvo."""
    if not settings.database_url:
        raise HTTPException(
            status_code=503,
            detail="DATABASE_URL não configurado. Adicione em backend/.env para persistir leads.",
        )
    try:
        pool = await get_pool()
        lead_id = uuid.uuid4()
        async with pool.acquire() as conn:
            existing_lead = await conn.fetchrow(
                "SELECT id FROM leads WHERE email = $1 OR telefone = $2",
                lead.email,
                lead.telefone
            )
            
            if existing_lead:
                return {
                    "success": True,
                    "message": "Lead já registrado (email ou telefone já existem)",
                    "lead_id": str(existing_lead["id"]),
                }

            await conn.execute(
                """
                INSERT INTO leads (id, nome, email, telefone, empresa)
                VALUES ($1, $2, $3, $4, $5)
                """,
                lead_id,
                lead.nome,
                lead.email,
                lead.telefone,
                lead.empresa,
            )
            row = await conn.fetchrow(
                "SELECT id FROM leads WHERE id = $1", lead_id
            )
        if not row:
            raise HTTPException(
                status_code=500,
                detail="Lead não foi persistido no banco. Tente novamente.",
            )
        return {
            "success": True,
            "message": "Lead registrado com sucesso",
            "lead_id": str(lead_id),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao registrar lead: {str(e)}")


@router.get("/list", dependencies=[Depends(require_admin_key)])
async def list_leads():
    """Lista todos os leads do PostgreSQL."""
    if not settings.database_url:
        raise HTTPException(
            status_code=503,
            detail="DATABASE_URL não configurado.",
        )
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, created_at, nome, email, telefone, empresa, COALESCE(contato_feito, false) as contato_feito FROM leads ORDER BY created_at DESC"
            )
        leads = [
            {
                "id": str(r["id"]),
                "timestamp": r["created_at"].isoformat() if r["created_at"] else "",
                "nome": r["nome"],
                "email": r["email"],
                "telefone": r["telefone"],
                "empresa": r["empresa"],
                "contato_feito": bool(r["contato_feito"]),
            }
            for r in rows
        ]
        return {"leads": leads}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao listar leads: {str(e)}")


class ContatoFeitoUpdate(BaseModel):
    contato_feito: bool


@router.patch("/{lead_id}/contato-feito", dependencies=[Depends(require_admin_key)])
async def update_contato_feito(lead_id: str, body: ContatoFeitoUpdate):
    """Atualiza o flag contato_feito de um lead."""
    if not settings.database_url:
        raise HTTPException(
            status_code=503,
            detail="DATABASE_URL não configurado.",
        )
    try:
        uid = uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de lead inválido.")
    try:
        pool = await get_pool()
        contato_feito = body.contato_feito
        async with pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE leads SET contato_feito = $1 WHERE id = $2",
                contato_feito,
                uid,
            )
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Lead não encontrado.")
        return {"success": True, "contato_feito": contato_feito}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar lead: {str(e)}")
