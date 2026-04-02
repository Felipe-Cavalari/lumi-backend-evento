"""Aplicação FastAPI principal."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import debug_logs, elevenlabs, leads, transcripts
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    if settings.database_url:
        try:
            from app.database import close_pool
            await close_pool()
        except Exception:
            pass


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
    if not settings.database_url:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "disconnected", "detail": "DATABASE_URL não configurado"},
        )
    try:
        from app.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "disconnected", "detail": str(e)},
        )
