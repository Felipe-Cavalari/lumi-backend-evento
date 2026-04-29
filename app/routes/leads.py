"""Rotas para gerenciamento de leads (Supabase)."""
import re
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.config import settings
from app.database import get_client
from app.security import require_admin_key

router = APIRouter(prefix="/api/leads", tags=["leads"])


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
async def register_lead(lead: LeadCreate):
    if not settings.supabase_url:
        raise HTTPException(status_code=503, detail="SUPABASE_URL não configurado.")
    try:
        db = get_client()

        existing = db.table("leads").select("id").eq("contato", lead.contato).execute()
        if existing.data:
            return {
                "success": True,
                "message": "Lead já registrado (contato já existe)",
                "lead_id": existing.data[0]["id"],
            }

        payload = {
            "id": str(uuid.uuid4()),
            "nome": lead.nome,
            "contato": lead.contato,
            "empresa": lead.empresa,
        }
        if lead.contato_feito is not None:
            payload["contato_feito"] = lead.contato_feito
        if lead.elevenlabs_conversation_id is not None:
            payload["elevenlabs_conversation_id"] = lead.elevenlabs_conversation_id

        result = db.table("leads").insert(payload).execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Lead não foi persistido no banco.")

        return {
            "success": True,
            "message": "Lead registrado com sucesso",
            "lead_id": result.data[0]["id"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao registrar lead: {str(e)}")


@router.get("/list", dependencies=[Depends(require_admin_key)])
async def list_leads():
    if not settings.supabase_url:
        raise HTTPException(status_code=503, detail="SUPABASE_URL não configurado.")
    try:
        db = get_client()
        result = db.table("leads").select(
            "id, created_at, nome, contato, empresa, contato_feito, elevenlabs_conversation_id"
        ).order("created_at", desc=True).execute()

        leads = [
            {
                "id": r["id"],
                "timestamp": r.get("created_at") or "",
                "nome": r["nome"],
                "contato": r["contato"],
                "empresa": r.get("empresa"),
                "contato_feito": bool(r.get("contato_feito", False)),
                "elevenlabs_conversation_id": r.get("elevenlabs_conversation_id"),
            }
            for r in result.data
        ]
        return {"leads": leads}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao listar leads: {str(e)}")


@router.get("/by-contato", dependencies=[Depends(require_admin_key)])
async def get_lead_by_contato(contato: str):
    if not settings.supabase_url:
        raise HTTPException(status_code=503, detail="SUPABASE_URL não configurado.")
    try:
        db = get_client()
        result = db.table("leads").select(
            "id, created_at, nome, contato, empresa, contato_feito, elevenlabs_conversation_id"
        ).eq("contato", contato).execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Lead não encontrado.")

        r = result.data[0]
        return {
            "id": r["id"],
            "timestamp": r.get("created_at") or "",
            "nome": r["nome"],
            "contato": r["contato"],
            "empresa": r.get("empresa"),
            "contato_feito": bool(r.get("contato_feito", False)),
            "elevenlabs_conversation_id": r.get("elevenlabs_conversation_id"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar lead: {str(e)}")


class ContatoFeitoUpdate(BaseModel):
    contato_feito: bool


class EmpresaUpdate(BaseModel):
    empresa: str


@router.patch("/{lead_id}/empresa", dependencies=[Depends(require_admin_key)])
async def update_empresa(lead_id: str, body: EmpresaUpdate):
    if not settings.supabase_url:
        raise HTTPException(status_code=503, detail="SUPABASE_URL não configurado.")
    try:
        uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de lead inválido.")
    try:
        db = get_client()
        result = db.table("leads").update({"empresa": body.empresa}).eq("id", lead_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Lead não encontrado.")
        return {"success": True, "empresa": body.empresa}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar lead: {str(e)}")


@router.patch("/{lead_id}/contato-feito", dependencies=[Depends(require_admin_key)])
async def update_contato_feito(lead_id: str, body: ContatoFeitoUpdate):
    if not settings.supabase_url:
        raise HTTPException(status_code=503, detail="SUPABASE_URL não configurado.")
    try:
        uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de lead inválido.")
    try:
        db = get_client()
        result = db.table("leads").update({"contato_feito": body.contato_feito}).eq("id", lead_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Lead não encontrado.")
        return {"success": True, "contato_feito": body.contato_feito}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar lead: {str(e)}")
