"""Rotas para integração com ElevenLabs API."""
from fastapi import APIRouter, HTTPException, Header
from typing import Optional
import httpx
import logging
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["elevenlabs"])


@router.post("/token/realtime-scribe")
async def get_realtime_scribe_token(
    authorization: Optional[str] = Header(None, alias="Authorization")
):
    """
    Gera um token single-use para Realtime Scribe (STT).
    
    Referência: https://elevenlabs.io/docs/developers/guides/cookbooks/speech-to-text/streaming#create-a-token
    """
    api_key = authorization.replace("Bearer ", "") if authorization else settings.elevenlabs_api_key
    
    if not api_key:
        raise HTTPException(status_code=401, detail="API key não fornecida")
    
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
async def get_signed_url(
    authorization: Optional[str] = Header(None, alias="Authorization")
):
    """
    Obtém uma signed URL para WebSocket do Conversational AI.
    
    Referência: https://elevenlabs.io/docs/conversational-ai/libraries/web-sockets#using-a-signed-url
    """
    api_key = authorization.replace("Bearer ", "") if authorization else settings.elevenlabs_api_key
    
    if not api_key:
        raise HTTPException(status_code=401, detail="API key não fornecida")
    
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
async def get_conversation_token(
    authorization: Optional[str] = Header(None, alias="Authorization")
):
    """
    Obtém um conversation token (WebRTC) para o SDK oficial da ElevenLabs.
    """
    api_key = authorization.replace("Bearer ", "") if authorization else settings.elevenlabs_api_key

    if not api_key:
        raise HTTPException(status_code=401, detail="API key não fornecida")

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
