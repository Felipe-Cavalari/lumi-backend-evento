FROM python:3.11.9-slim

WORKDIR /app

# Instalar dependências do sistema necessárias para pydub/audioop
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código da aplicação
COPY app/ ./app/

# Copiar configuração e scripts do Alembic (necessários para rodar migrations no deploy)
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY docker-entrypoint.sh ./

# Criar diretórios de dados e usuário não-root
RUN chmod +x docker-entrypoint.sh \
    && mkdir -p data/audio data/debug/browser_logs data/transcripts \
    && addgroup --system appgroup \
    && adduser --system --ingroup appgroup appuser \
    && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# O entrypoint roda `alembic upgrade head` e então executa o CMD abaixo.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
