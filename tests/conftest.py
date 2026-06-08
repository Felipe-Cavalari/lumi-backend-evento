"""Fixtures de teste para a API de leads.

Estratégia de isolamento:
- Usa um banco dedicado ``lumi_test`` (derivado da DATABASE_URL do .env).
- Aplica as migrations reais do Alembic nesse banco (testa o schema de verdade).
- Trunca a tabela ``leads`` antes de cada teste, garantindo isolamento.
- Injeta um pool apontando para o banco de teste em ``app.database._pool`` e
  sobrescreve ``settings.database_url`` / ``settings.admin_api_key`` em runtime.
"""
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import database
from app.config import settings
from app.main import app

ADMIN_KEY = "test-admin-key"
TEST_DB_NAME = "lumi_test"
ROOT = Path(__file__).resolve().parent.parent


def _swap_db(url: str, dbname: str) -> str:
    """Troca o nome do banco no DSN, preservando user/senha/host/porta."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{dbname}"))


@pytest.fixture(scope="session")
def test_db_url() -> str:
    base = settings.database_url
    if not base:
        pytest.skip("DATABASE_URL não configurado — testes de integração ignorados.")
    return _swap_db(base, TEST_DB_NAME)


@pytest.fixture(scope="session", autouse=True)
def _prepare_database(test_db_url):
    """Cria o banco de teste (se necessário) e aplica as migrations uma vez."""
    maintenance = _swap_db(settings.database_url, "postgres")

    async def _create_db():
        conn = await asyncpg.connect(dsn=maintenance, ssl=False)
        try:
            exists = await conn.fetchval(
                "select 1 from pg_database where datname = $1", TEST_DB_NAME
            )
            if not exists:
                await conn.execute(f'create database "{TEST_DB_NAME}"')
        finally:
            await conn.close()

    asyncio.run(_create_db())

    # Aplica as migrations no banco de teste. O env.py do Alembic lê
    # DATABASE_URL do ambiente; load_dotenv (override=False) não sobrescreve
    # uma variável já definida, então o valor abaixo prevalece.
    env = {**os.environ, "DATABASE_URL": test_db_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        check=True,
    )
    yield


@pytest_asyncio.fixture
async def client(test_db_url, monkeypatch):
    """Cliente HTTP async ligado ao app, com pool apontando para o banco de teste."""
    monkeypatch.setattr(settings, "admin_api_key", ADMIN_KEY)
    monkeypatch.setattr(settings, "database_url", test_db_url)

    pool = await asyncpg.create_pool(dsn=test_db_url, ssl=False, min_size=1, max_size=5)
    database._pool = pool
    # Isolamento: cada teste começa com a tabela vazia.
    await pool.execute("truncate leads restart identity cascade")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await pool.close()
    database._pool = None


@pytest.fixture
def admin_headers() -> dict:
    return {"X-Admin-Key": ADMIN_KEY}
