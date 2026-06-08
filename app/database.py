"""Pool de conexões PostgreSQL (asyncpg)."""
import asyncpg

from app.config import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    """Cria o pool de conexões (idempotente)."""
    global _pool
    if _pool is None:
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL não configurado")
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=10,
            command_timeout=15,
            # Rede interna do Docker no Coolify → tráfego não sai do host.
            # SSL não é necessário internamente; habilite se o Postgres exigir.
            ssl=False,
        )


async def close_pool() -> None:
    """Fecha o pool de conexões."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """Retorna o pool já inicializado."""
    if _pool is None:
        raise RuntimeError("Pool de banco não inicializado")
    return _pool
