#!/bin/sh
# Entrypoint de produção: aplica as migrations do banco antes de subir a API.
# Roda uma única vez por container (antes do uvicorn), evitando race entre workers.
set -e

echo "[entrypoint] Aplicando migrations (alembic upgrade head)..."
alembic upgrade head

echo "[entrypoint] Migrations aplicadas. Iniciando aplicação..."
exec "$@"
