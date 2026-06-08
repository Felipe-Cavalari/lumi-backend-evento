"""Rotas para integração com ElevenLabs API."""
import time

from fastapi import APIRouter, HTTPException, Request
import httpx
import logging
from app.config import settings
from app.cache import cache_get, cache_set
from app.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["elevenlabs"])

# Fix C-02: teto de uso GLOBAL (somado ao rate limit por IP) para proteger a
# quota/custo da conta ElevenLabs mesmo sob abuso distribuído de muitos IPs.
# São endpoints públicos do widget anônimo — sem este teto, N clientes
# legítimos/maliciosos drenariam a conta. Ajuste conforme a escala do evento.
# Janela fixa em memória (single-process; para multi-instância migrar p/ Redis).
_TOKEN_QUOTA_WINDOW = 3600  # 1 hora
_TOKEN_QUOTA_MAX = 2000  # gerações de token/signed-url por hora no total


def _enforce_global_token_quota() -> None:
    """Incrementa e checa o contador global de gerações de token na janela atual."""
    window = int(time.time()) // _TOKEN_QUOTA_WINDOW
    key = f"elevenlabs:token_mints:{window}"
    count = (cache_get(key, ttl=_TOKEN_QUOTA_WINDOW) or 0) + 1
    cache_set(key, count, ttl=_TOKEN_QUOTA_WINDOW)
    if count > _TOKEN_QUOTA_MAX:
        logger.warning("Teto global de geração de tokens ElevenLabs atingido (%d)", count)
        raise HTTPException(
            status_code=429,
            detail="Limite de geração de tokens atingido. Tente novamente mais tarde.",
        )


@router.post("/token/realtime-scribe")
@limiter.limit("30/minute")
async def get_realtime_scribe_token(request: Request):
    """
    Gera um token single-use para Realtime Scribe (STT).

    Referência: https://elevenlabs.io/docs/developers/guides/cookbooks/speech-to-text/streaming#create-a-token
    """
    # Fix C-02: usa SEMPRE a chave do servidor; o cliente não pode injetar
    # credencial via header. Endpoint público protegido por rate limit + teto global.
    _enforce_global_token_quota()
    api_key = settings.elevenlabs_api_key

    if not api_key:
        raise HTTPException(status_code=503, detail="ELEVENLABS_API_KEY não configurada no servidor")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.elevenlabs.io/v1/single-use-token/realtime-scribe",
                headers={
                    "xi-api-key": api_key,
                },
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()
            return {"token": data.get("token")}
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Erro ao gerar token: {e.response.text}"
        )
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Erro de conexão: {str(e)}")


@router.get("/conversation/signed-url")
@limiter.limit("30/minute")
async def get_signed_url(request: Request):
    """
    Obtém uma signed URL para WebSocket do Conversational AI.

    Referência: https://elevenlabs.io/docs/conversational-ai/libraries/web-sockets#using-a-signed-url
    """
    # Fix C-02: chave do servidor sempre; protegido por rate limit + teto global.
    _enforce_global_token_quota()
    api_key = settings.elevenlabs_api_key

    if not api_key:
        raise HTTPException(status_code=503, detail="ELEVENLABS_API_KEY não configurada no servidor")

    agent_id = settings.agent_id_value
    if not agent_id:
        raise HTTPException(status_code=400, detail="AGENT_ID ou ELEVENLABS_AGENT_ID não configurado")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.elevenlabs.io/v1/convai/conversation/get-signed-url?agent_id={agent_id}",
                headers={
                    "xi-api-key": api_key,
                },
                timeout=10.0,
            )
            logger.info("ElevenLabs /signed-url status=%d body=%s", response.status_code, response.text[:500])
            response.raise_for_status()
            data = response.json()
            signed_url = data.get("signed_url")
            if not signed_url:
                logger.error("ElevenLabs retornou signed_url nulo. Resposta completa: %s", data)
                raise HTTPException(
                    status_code=502,
                    detail=f"ElevenLabs retornou signed_url nulo. Resposta: {data}"
                )
            return {"signed_url": signed_url}
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        logger.error("ElevenLabs /signed-url HTTP error status=%d body=%s", e.response.status_code, e.response.text)
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Erro ao obter signed URL: {e.response.text}"
        )
    except httpx.RequestError as e:
        logger.error("ElevenLabs /signed-url request error: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Erro de conexão: {str(e)}")


@router.get("/conversation/token")
@limiter.limit("30/minute")
async def get_conversation_token(request: Request):
    """
    Obtém um conversation token (WebRTC) para o SDK oficial da ElevenLabs.
    """
    # Fix C-02: chave do servidor sempre; protegido por rate limit + teto global.
    _enforce_global_token_quota()
    api_key = settings.elevenlabs_api_key

    if not api_key:
        raise HTTPException(status_code=503, detail="ELEVENLABS_API_KEY não configurada no servidor")

    agent_id = settings.agent_id_value
    if not agent_id:
        raise HTTPException(status_code=400, detail="AGENT_ID ou ELEVENLABS_AGENT_ID não configurado")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.elevenlabs.io/v1/convai/conversation/token?agent_id={agent_id}",
                headers={
                    "xi-api-key": api_key,
                },
                timeout=10.0,
            )
            logger.info("ElevenLabs /conversation/token status=%d body=%s", response.status_code, response.text[:500])
            response.raise_for_status()
            data = response.json()
            token = data.get("conversation_token") or data.get("token")
            if not token:
                logger.error("ElevenLabs retornou token nulo. Resposta completa: %s", data)
                raise HTTPException(
                    status_code=502,
                    detail=f"ElevenLabs retornou token nulo. Resposta: {data}"
                )
            return {"conversation_token": token}
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        logger.error("ElevenLabs /conversation/token HTTP error status=%d body=%s", e.response.status_code, e.response.text)
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Erro ao obter conversation token: {e.response.text}"
        )
    except httpx.RequestError as e:
        logger.error("ElevenLabs /conversation/token request error: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Erro de conexão: {str(e)}")
