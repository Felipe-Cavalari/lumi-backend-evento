"""Rotas para integração com ElevenLabs API."""
from fastapi import APIRouter, HTTPException, Header
from typing import Optional
import httpx
from app.config import settings

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
            agent_id = settings.agent_id_value
            response = await client.get(
                f"https://api.elevenlabs.io/v1/convai/conversation/get-signed-url?agent_id={agent_id}",
                headers={
                    "xi-api-key": api_key,
                },
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()
            return {"signed_url": data.get("signed_url")}
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Erro ao obter signed URL: {e.response.text}"
        )
    except httpx.RequestError as e:
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
            response.raise_for_status()
            data = response.json()
            return {"conversation_token": data.get("conversation_token") or data.get("token")}
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Erro ao obter conversation token: {e.response.text}"
        )
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Erro de conexão: {str(e)}")
