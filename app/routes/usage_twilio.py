"""Rota GET /api/usage/twilio — métricas de uso e custo Twilio."""
import logging
from datetime import date

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.services.twilio_service import get_twilio_usage

router = APIRouter(prefix="/api/usage", tags=["usage"])
logger = logging.getLogger(__name__)


@router.get("/twilio")
async def twilio_usage(
    start_date: date = Query(default=None, description="Data de início (YYYY-MM-DD)"),
    end_date: date = Query(default=None, description="Data de fim (YYYY-MM-DD)"),
):
    """Retorna saldo, custos por categoria e uso diário da Twilio."""
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

    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise HTTPException(
            status_code=503,
            detail="Credenciais Twilio não configuradas (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN)",
        )

    try:
        return await get_twilio_usage(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            start_date=start_date,
            end_date=end_date,
        )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.error("Twilio API error %s: %s", status, exc.response.text[:200])
        if status == 401:
            raise HTTPException(status_code=502, detail="Credenciais Twilio inválidas")
        raise HTTPException(status_code=502, detail=f"Erro na API Twilio: {status}")
    except httpx.TimeoutException:
        logger.error("Twilio API timeout")
        raise HTTPException(status_code=504, detail="Timeout na API Twilio")
    except Exception as exc:
        logger.exception("Twilio usage unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Erro interno ao buscar dados Twilio")
