"""Rota GET /api/usage/elevenlabs — métricas de uso e custo ElevenLabs."""
import logging
from datetime import date

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.services.elevenlabs_usage_service import get_elevenlabs_usage

router = APIRouter(prefix="/api/usage", tags=["usage"])
logger = logging.getLogger(__name__)


@router.get("/elevenlabs")
async def elevenlabs_usage(
    start_date: date = Query(default=None, description="Data de início (YYYY-MM-DD)"),
    end_date: date = Query(default=None, description="Data de fim (YYYY-MM-DD)"),
):
    """Retorna custo total, uso de caracteres e uso diário da ElevenLabs."""
    today = date.today()
    if end_date is None:
        end_date = today
    if start_date is None:
        start_date = end_date.replace(day=1)

    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date não pode ser posterior a end_date",
        )

    if not settings.elevenlabs_api_key:
        raise HTTPException(
            status_code=503,
            detail="Credencial ElevenLabs não configurada (ELEVENLABS_API_KEY)",
        )

    try:
        return await get_elevenlabs_usage(
            api_key=settings.elevenlabs_api_key,
            start_date=start_date,
            end_date=end_date,
        )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.error("ElevenLabs API error %s: %s", status, exc.response.text[:200])
        if status == 401:
            raise HTTPException(status_code=502, detail="Credencial ElevenLabs inválida")
        raise HTTPException(status_code=502, detail=f"Erro na API ElevenLabs: {status}")
    except httpx.TimeoutException:
        logger.error("ElevenLabs API timeout")
        raise HTTPException(status_code=504, detail="Timeout na API ElevenLabs")
    except Exception as exc:
        logger.exception("ElevenLabs usage unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Erro interno ao buscar dados ElevenLabs")
