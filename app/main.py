"""Aplicação FastAPI principal."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import debug_logs, elevenlabs, leads, transcripts, usage_twilio, usage_elevenlabs
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    lifespan=lifespan,
    title="ElevenLabs AgentAI Backend",
    description="Backend para gerenciamento de tokens e signed URLs da ElevenLabs",
    version="1.0.0",
)

# Configurar CORS — usa a lista CORS_ORIGINS do .env (padrão: http://localhost:3000)
cors_origins = settings.cors_origins_list

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Registrar rotas
app.include_router(elevenlabs.router)
app.include_router(leads.router)
app.include_router(transcripts.router)
app.include_router(debug_logs.router)
app.include_router(usage_twilio.router)
app.include_router(usage_elevenlabs.router)


@app.get("/")
async def root():
    """Endpoint raiz."""
    return {"message": "ElevenLabs AgentAI Backend API", "status": "running"}


@app.get("/health")
async def health():
    """Health check básico (API)."""
    return {"status": "healthy"}


@app.get("/api/health")
async def api_health():
    """Health check incluindo conexão com banco de dados."""
    if not settings.supabase_url:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "disconnected", "detail": "SUPABASE_URL não configurado"},
        )
    try:
        from app.database import get_client
        get_client().table("leads").select("id").limit(1).execute()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "disconnected", "detail": str(e)},
        )
