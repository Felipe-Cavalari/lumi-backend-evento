"""Conexão PostgreSQL (Supabase) para persistência de leads."""
import asyncio
from typing import Optional
import asyncpg
from app.config import settings

_pool: Optional[asyncpg.Pool] = None

RETRY_DELAYS = [2, 4, 6]
CONNECTION_TIMEOUT = 30


async def get_pool() -> asyncpg.Pool:
    """Retorna o pool de conexões. Cria com retry e inicializa a tabela se necessário."""
    global _pool
    if _pool is None:
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL não configurado")
        url = settings.database_url
        if "sslmode=" not in url and "?" not in url:
            url = f"{url}?sslmode=require"
        elif "sslmode=" not in url and "?" in url:
            url = f"{url}&sslmode=require"
        last_error = None
        for i, delay in enumerate(RETRY_DELAYS):
            try:
                _pool = await asyncio.wait_for(
                    asyncpg.create_pool(
                        url,
                        min_size=1,
                        max_size=5,
                        command_timeout=60,
                        timeout=CONNECTION_TIMEOUT,
                    ),
                    timeout=CONNECTION_TIMEOUT + 5,
                )
                await _init_leads_table()
                return _pool
            except Exception as e:
                last_error = e
                _pool = None
                if i < len(RETRY_DELAYS) - 1:
                    await asyncio.sleep(delay)
                else:
                    raise last_error
    return _pool


async def _init_leads_table() -> None:
    """Cria a tabela leads se não existir."""
    pool = _pool
    if not pool:
        return
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                nome TEXT NOT NULL,
                email TEXT NOT NULL,
                telefone TEXT NOT NULL,
                empresa TEXT NOT NULL
            )
        """)
        await conn.execute("""
            ALTER TABLE leads ADD COLUMN IF NOT EXISTS contato_feito BOOLEAN NOT NULL DEFAULT FALSE
        """)


async def close_pool() -> None:
    """Fecha o pool de conexões."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
