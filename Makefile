.PHONY: help install run dev prod docker-build docker-run test

# Configurações
VENV ?= .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
HOST ?= 0.0.0.0
PORT ?= 8000
APP := app.main:app

help: ## Lista os comandos disponíveis
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Cria o virtualenv e instala as dependências
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

run: dev ## Alias para 'dev'

dev: ## Roda o servidor em modo desenvolvimento (com reload)
	$(VENV)/bin/uvicorn $(APP) --host $(HOST) --port $(PORT) --reload

prod: ## Roda o servidor em modo produção
	$(VENV)/bin/uvicorn $(APP) --host $(HOST) --port $(PORT) --workers 1

test: ## Roda a suíte de testes (cria/usa o banco lumi_test)
	$(VENV)/bin/pytest -v

docker-build: ## Builda a imagem Docker
	docker build -t lumi-backend-evento .

docker-run: ## Roda o container Docker
	docker run --rm -p $(PORT):8000 --env-file .env lumi-backend-evento
