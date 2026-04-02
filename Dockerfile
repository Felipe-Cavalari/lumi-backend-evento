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

# Criar diretórios de dados
RUN mkdir -p data/audio data/debug/browser_logs data/transcripts

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
