# PROJECT.md — lumi-evento-service

> Análise técnica gerada automaticamente em 2026-04-02.

---

## 1. Visão Geral

`lumi-evento-service` é um backend FastAPI que atua como proxy seguro entre um frontend JavaScript e a API da ElevenLabs. Ele expõe endpoints para geração de tokens de voz (STT/TTS), gerenciamento de leads num banco PostgreSQL (Supabase), persistência de transcrições e áudios em disco, e captura de logs do console do navegador.

O serviço foi projetado para eventos presenciais onde um agente de IA conversacional (Lumi) coleta o contato dos participantes via voz e persiste essas interações para uso posterior.

---

## 2. Arquitetura

```
lumi-evento-service/
├── app/
│   ├── __init__.py          — package marker
│   ├── main.py              — entry point FastAPI, CORS, lifespan, rotas raiz
│   ├── config.py            — configurações via pydantic-settings (vars de ambiente)
│   ├── database.py          — pool asyncpg com retry, init de tabela leads
│   └── routes/
│       ├── __init__.py      — re-exporta todos os routers
│       ├── elevenlabs.py    — proxy de tokens ElevenLabs (STT scribe, signed URL, WS token)
│       ├── leads.py         — CRUD de leads no PostgreSQL
│       ├── transcripts.py   — salva transcrições STT (.txt) e áudios TTS (.mp3/wav/pcm) em disco
│       └── debug_logs.py    — recebe lotes de logs do browser, persiste em .log
├── requirements.txt
├── runtime.txt              — python-3.11.9
└── .env.example
```

**Dependências externas:**
| Pacote | Papel |
|---|---|
| `fastapi` | Framework HTTP async |
| `uvicorn[standard]` | Servidor ASGI |
| `pydantic` / `pydantic-settings` | Modelos de dados e configuração |
| `httpx` | Cliente HTTP async para proxy ElevenLabs |
| `asyncpg` | Driver PostgreSQL async |
| `pydub` | Conversão PCM→MP3 (requer `ffmpeg` no PATH) |
| `audioop-lts` | Compatibilidade `audioop` para Python ≥ 3.13 |

---

## 3. Fluxo Principal

```
[Browser/Frontend]
    │
    ├─ POST /api/token/realtime-scribe   ─→ elevenlabs.py → ElevenLabs API → token STT
    ├─ GET  /api/conversation/signed-url ─→ elevenlabs.py → ElevenLabs API → WebSocket URL
    ├─ GET  /api/conversation/token      ─→ elevenlabs.py → ElevenLabs API → WebRTC token
    │
    ├─ POST /api/leads/register          ─→ leads.py → asyncpg → PostgreSQL (Supabase)
    ├─ GET  /api/leads/list              ─→ leads.py ← asyncpg ← PostgreSQL
    ├─ PATCH /api/leads/{id}/contato-feito ─→ leads.py → asyncpg
    │
    ├─ POST /api/transcripts/stt         ─→ transcripts.py → data/transcripts/{email}/*.txt
    ├─ POST /api/transcripts/tts         ─→ transcripts.py → pydub → data/audio/{email}/*.mp3
    │
    └─ POST /api/debug/browser-logs      ─→ debug_logs.py → data/debug/browser_logs/*.log
```

**Startup (lifespan):**  
Sem ação no startup. No shutdown, fecha o pool asyncpg se `DATABASE_URL` estiver configurado.

**Criação de schema:**  
A tabela `leads` (com `ALTER TABLE ADD COLUMN IF NOT EXISTS contato_feito`) é inicializada na primeira chamada que aciona `get_pool()` (lazy init).

---

## 4. Configuração

| Variável de ambiente  | Obrigatória | Default                 | Descrição                                                                         |
| --------------------- | ----------- | ----------------------- | --------------------------------------------------------------------------------- |
| `ELEVENLABS_API_KEY`  | ✅ Sim      | —                       | Chave da API ElevenLabs                                                           |
| `AGENT_ID`            | Não         | `None`                  | ID do agente ElevenLabs (aliases: `ELEVENLABS_AGENT_ID`)                          |
| `ELEVENLABS_AGENT_ID` | Não         | `None`                  | Alias alternativo para o agent ID                                                 |
| `DATABASE_URL`        | Não         | `None`                  | Connection string PostgreSQL (Supabase). Sem ela, endpoints de leads retornam 503 |
| `CORS_ORIGINS`        | Não         | `http://localhost:3000` | Lista CSV de origens permitidas no CORS                                           |

**Arquivo de config:** `.env` na raiz do repositório (detectado por `Path(__file__).resolve().parent.parent`).

> ⚠️ Atenção: o CORS está configurado em `main.py` com `allow_origins=["*"]`, ignorando `CORS_ORIGINS` em produção (veja seção de problemas).

---

## 5. Como Rodar

```bash
# 1. Instalar dependências (recomendado: venv)
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install -r requirements.txt

# 2. Configurar variáveis de ambiente
copy .env.example .env
# Editar .env com os valores reais

# 3. Instalar ffmpeg (necessário para conversão de áudio PCM→MP3)
# macOS:  brew install ffmpeg
# Ubuntu: sudo apt-get install ffmpeg
# Windows: https://ffmpeg.org/download.html (adicionar ao PATH)

# 4. Executar
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 5. Checar saúde
curl http://localhost:8000/health
curl http://localhost:8000/api/health   # inclui teste de banco
```

**Documentação interativa (Swagger):** `http://localhost:8000/docs`

---

## 6. Decisões Técnicas

- **FastAPI + asyncpg:** Stack totalmente async para evitar blocking I/O nas chamadas à ElevenLabs e ao PostgreSQL simultaneamente.
- **Proxy de tokens:** A API key da ElevenLabs nunca é exposta ao frontend; o backend age como intermediário, aceitando no header `Authorization: Bearer <key>` como fallback de desenvolvimento.
- **pydantic-settings:** Centraliza toda configuração num único objeto `Settings`, com validação em tempo de startup.
- **Pool com retry:** `database.py` implementa 3 tentativas com delays crescentes (2s, 4s, 6s) para robustez em ambientes cloud com cold-start.
- **Armazenamento em disco:** Transcrições e áudios são salvos localmente em `data/`. Estratégia adequada para prova de conceito em evento; não escala horizontalmente.
- **audioop-lts:** Condicional no `requirements.txt` (`python_version >= "3.13"`) para compatibilidade, pois `audioop` foi removido da stdlib no Python 3.13.

---

## 7. Problemas Encontrados

### 7.1 Segurança

| #    | Arquivo          | Linha        | Descrição                                                                                                                                                                                                                                                                                                                                                                                    | Severidade |
| ---- | ---------------- | ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| S-01 | `main.py`        | 33           | `allow_origins=["*"]` ignora `CORS_ORIGINS` configurado. Qualquer origem consegue fazer requisições — inclusive em produção. A variável `cors_origins` é calculada mas descartada.                                                                                                                                                                                                           | **Alta**   |
| S-02 | `elevenlabs.py`  | 19, 54, 92   | O endpoint aceita `Authorization: Bearer <key>` do cliente e usa essa chave diretamente nas chamadas à ElevenLabs. Um cliente malicioso pode usar chaves de API de terceiros por meio do serviço. Não há whitelist de chaves válidas.                                                                                                                                                        | **Alta**   |
| S-03 | `leads.py`       | 97           | `lead_id` recebido como `str` na URL é convertido para `uuid.UUID`, mas antes de qualquer validação de banco. Se um atacante enviar `lead_id` com caracteres especiais que não formem UUID válido, o erro é retornado como 400 (correto) — mas a mensagem expõe detalhes internos. Baixo risco, mas a ausência de autenticação em todos os endpoints de leads (list, patch) é o maior vetor. | **Alta**   |
| S-04 | `leads.py`       | 61–89        | `GET /api/leads/list` e `PATCH /api/leads/{id}/contato-feito` não têm nenhuma autenticação/autorização. Qualquer um que conheça a URL pode listar todos os leads capturados no evento.                                                                                                                                                                                                       | **Alta**   |
| S-05 | `transcripts.py` | 114, 231     | O `filepath` absoluto do servidor é retornado na resposta JSON. Isso revela a estrutura interna de diretórios do servidor ao cliente.                                                                                                                                                                                                                                                        | **Média**  |
| S-06 | `debug_logs.py`  | 63           | Idem — `filepath` do servidor retornado na resposta.                                                                                                                                                                                                                                                                                                                                         | **Média**  |
| S-07 | `transcripts.py` | 45–47, 63–65 | Sanitização do email usa lista branca `isalnum() or c in ["_", "-"]`, mas `lead_email` não é validado como e-mail real (não há `EmailStr` do pydantic). Um payload `lead_email: "../../etc"` seria sanitizado para `______etc` — eficaz contra path traversal. Cobertura adequada, porém seria mais idiomático usar `pydantic.EmailStr`.                                                     | **Baixa**  |

### 7.2 Bugs Potenciais

| #    | Arquivo          | Linha   | Descrição                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | Severidade |
| ---- | ---------------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| B-01 | `main.py`        | 12–17   | `close_pool()` só é chamado no shutdown se `settings.database_url` estiver configurado **no momento do shutdown**. Se a variável foi alterada dinamicamente (incomum, mas possível em testes), o pool pode não ser fechado. Risco baixo em produção.                                                                                                                                                                                                                                                                                                                    | **Baixa**  |
| B-02 | `database.py`    | 20–23   | Lógica para adicionar `sslmode=require` à URL falha silenciosamente se a URL já contiver `sslmode=` mas com outro valor (ex.: `sslmode=disable`). O `elif` verifica a ausência de ambos `sslmode=` e `?`, mas a condição `"sslmode=" not in url` é suficiente — o `elif` não é executado quando a URL já tem `?` mas não tem `sslmode=`, o que geraria `url=url&sslmode=require` sem o `?`. **Aguarda análise:** se o `url` tem `?` mas não tem `sslmode=`, entra no `elif` e concatena `&sslmode=require` — correto. Comportamento funcional, mas a leitura é confusa. | **Baixa**  |
| B-03 | `database.py`    | 42      | `if i < len(RETRY_DELAYS) - 1` só faz sleep nas tentativas não-finais. Na última tentativa, re-levanta `last_error`. Lógica correta, mas o loop poderia ser mais claro com `enumerate` e verificação explícita.                                                                                                                                                                                                                                                                                                                                                         | **Baixa**  |
| B-04 | `transcripts.py` | 173–213 | Fallback em cadeia (MP3 → WAV → PCM) usa `mp3_bytes` como nome de variável mesmo quando o formato é WAV ou PCM — variável nomeada enganosamente. Se `AudioSegment()` levanta exceção mas `audio_segment` permanece `None`, o bloco `except` interno testa `if audio_segment is not None` e cai no `else`, salvando PCM cru. Comportamento correto, mas frágil.                                                                                                                                                                                                          | **Média**  |
| B-05 | `elevenlabs.py`  | 65      | `agent_id` é buscado via `settings.agent_id_value` duas vezes (linhas 59 e 65) e a segunda atribuição sobrescreve a variável local sem propósito. Código morto redundante.                                                                                                                                                                                                                                                                                                                                                                                              | **Baixa**  |
| B-06 | `leads.py`       | 29–44   | O lead é inserido com `uuid.uuid4()` gerado pelo Python, não pelo banco. Há uma query extra `SELECT id FROM leads WHERE id = $1` para confirmar persistência — desnecessária quando se usa INSERT + RETURNING. Se a inserção falhar (constraint violation etc.), a exceção já propaga antes do SELECT.                                                                                                                                                                                                                                                                  | **Baixa**  |

### 7.3 Código Morto / Antipadrões

| #    | Arquivo          | Linha | Descrição                                                                                                                                                                                    | Severidade |
| ---- | ---------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| A-01 | `main.py`        | 28–29 | `cors_origins` é calculado e printado mas nunca usado — o middleware usa `["*"]` hardcoded.                                                                                                  | **Média**  |
| A-02 | `config.py`      | 30–31 | `if isinstance(cors_str, list)` nunca será `True` — `cors_str` é sempre `str` ou `None` dado o tipo `Optional[str]` do campo.                                                                | **Baixa**  |
| A-03 | `transcripts.py` | 237   | `import traceback` dentro do bloco `except` (import tardio). Funciona, mas é antipadrão — deve ser movido para o topo do arquivo.                                                            | **Baixa**  |
| A-04 | `leads.py`       | 2     | `import uuid` é usado, mas o UUID poderia ser gerado pelo banco via `DEFAULT gen_random_uuid()` (já está no schema), eliminando a dependência do lado Python.                                | **Baixa**  |
| A-05 | `config.py`      | 39–43 | Uso de classe interna `class Config` é estilo pydantic v1. Em pydantic v2 o correto é `model_config = SettingsConfigDict(...)`. Funciona por compatibilidade, mas gera `DeprecationWarning`. | **Média**  |

### 7.4 Falta de Validação de Entrada

| #    | Arquivo          | Linha | Descrição                                                                                                                                                                                                                                                            | Severidade |
| ---- | ---------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| V-01 | `leads.py`       | 12–16 | `LeadCreate` não valida `email` com `EmailStr`, `telefone` com regex, nem limita tamanho dos campos. Um bot pode inserir textos arbitrários de qualquer tamanho.                                                                                                     | **Média**  |
| V-02 | `transcripts.py` | 15–29 | `TranscriptData.speaker` e `AudioData.speaker` são `str` livres. O código usa condicionais `if speaker == "agent"` sem impedir valores como `"../etc"`. A sanitização posterior protege o filesystem, mas validar com `Literal["user", "agent"]` seria mais correto. | **Baixa**  |
| V-03 | `transcripts.py` | 26    | `audio_base64` não tem limite de tamanho. Um payload malicioso pode enviar centenas de MB de base64, causando OOM no servidor.                                                                                                                                       | **Alta**   |
| V-04 | `debug_logs.py`  | 25    | `entries: List[BrowserLogEntry]` sem limite máximo — um payload com milhares de entradas pode causar slow down ou OOM.                                                                                                                                               | **Média**  |

---

## 8. Performance

| #    | Arquivo          | Descrição                                                                                                                                                                                                                           | Impacto | Sugestão                                                                                                                                      |
| ---- | ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| P-01 | `transcripts.py` | `base64.b64decode(audio.audio_base64)` carrega o áudio inteiro em memória (pode ser vários MB por requisição).                                                                                                                      | Médio   | Limitar o tamanho máximo do payload via `max_size` no Starlette ou validação Pydantic antes do decode.                                        |
| P-02 | `transcripts.py` | `AudioSegment(audio_bytes, ...)` + `export(mp3_buffer)` são operações síncronas CPU-bound executadas na thread do event loop. Com múltiplas conversões simultâneas, bloqueia o loop asyncio.                                        | Alto    | Executar via `asyncio.get_event_loop().run_in_executor(None, ...)` para isolar em thread pool.                                                |
| P-03 | `transcripts.py` | `io.BytesIO()` + `mp3_buffer.getvalue()` mantém o MP3 completo em memória antes de escrever em disco. Para áudios longos (>10 min), pode ser centenas de MB.                                                                        | Médio   | Usar pipe direto de `pydub.export()` para arquivo em disco (`audio_segment.export(filepath, format="mp3")`), evitando o buffer intermediário. |
| P-04 | `database.py`    | Pool com `max_size=5` é fixo. Em picos de tráfego num evento presencial com muitos acessos simultâneos, conexões ficam enfileiradas.                                                                                                | Médio   | Tornar `max_size` configurável via variável de ambiente.                                                                                      |
| P-05 | `leads.py`       | `register_lead` faz INSERT + SELECT separados para confirmar persistência. Dois round-trips ao banco onde um bastaria.                                                                                                              | Baixo   | Usar `INSERT ... RETURNING id` num único statement, eliminando o SELECT.                                                                      |
| P-06 | `database.py`    | `_init_leads_table` é chamada toda vez que o pool é criado (restart do serviço), executando `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE`. Para tabelas com muitas linhas, o `ALTER TABLE ... IF NOT EXISTS` pode travar brevemente. | Baixo   | Em produção, prefira migrações controladas (ex.: Alembic) em vez de DDL inline no código.                                                     |
| P-07 | `debug_logs.py`  | Arquivo de log aberto em modo append (`"a"`) por requisição, sem buffer ou batch persistido em memória. Para sessões com alto volume de logs, o overhead de open/close por requisição é mensurável.                                 | Baixo   | Considerar buffer em memória (lista em módulo) com flush periódico ou por tamanho.                                                            |

---

## 9. Requirements.txt — Análise

O `requirements.txt` atual está correto e alinhado com os imports reais. Abaixo a versão comentada por categoria:

```
# Framework HTTP
fastapi>=0.104.0
uvicorn[standard]>=0.24.0

# Configuração e modelos
pydantic>=2.0.0
pydantic-settings>=2.0.0
python-dotenv>=1.0.0

# Cliente HTTP (proxy ElevenLabs)
httpx>=0.25.0

# Banco de dados
asyncpg>=0.29.0

# Áudio
pydub>=0.25.1
audioop-lts>=0.2.0; python_version >= "3.13"
```

**Stdlib utilizada (não vai para requirements.txt):**
`asyncio`, `base64`, `datetime`, `io`, `os`, `pathlib`, `re`, `traceback`, `typing`, `uuid`

**Dependência implícita não listada:**

- `ffmpeg` — binário externo, não é pacote Python. Deve ser documentado no README.

---

## 10. Resumo Executivo

### Saúde geral do código: **Regular**

O código é funcional, bem estruturado e usa boas práticas async. Os maiores riscos são de segurança (ausência de autenticação) e de estabilidade sob carga (operações síncronas bloqueantes no event loop).

---

### Top 3 Problemas Mais Urgentes

1. **[S-04] Ausência de autenticação nos endpoints de leads** — `GET /api/leads/list` e `PATCH` são públicos. Qualquer crawler pode vazar dados de contato dos participantes do evento.
2. **[S-01] CORS aberto (`allow_origins=["*"]`)** — a configuração `CORS_ORIGINS` no `.env` é calculada mas ignorada; o serviço aceita requisições de qualquer origem em produção.
3. **[V-03] Sem limite de tamanho no payload de áudio** — um payload base64 de 500 MB pode ser enviado sem restrição, causando OOM ou denial of service.

---

### Top 3 Melhorias de Performance Mais Impactantes

1. **[P-02] Conversão de áudio no event loop** — mover `AudioSegment` + `export` para `run_in_executor` previne travamento do loop asyncio durante eventos com alta concorrência.
2. **[P-03] Buffer intermediário do MP3 em memória** — escrever diretamente em disco via `audio_segment.export(filepath)` elimina cópia desnecessária em memória.
3. **[P-01] Payload base64 sem limite** — adicionar validação de tamanho máximo antes do decode reduz risco de OOM e melhora a resiliência geral.

---

### Estimativa de Esforço para Correção

| Grupo                                                                 | Itens            | Esforço estimado |
| --------------------------------------------------------------------- | ---------------- | ---------------- |
| Autenticação (API key ou Bearer token simples nos endpoints de leads) | S-03, S-04       | 2–4 horas        |
| Corrigir CORS para usar `CORS_ORIGINS` real                           | S-01, A-01       | 30 minutos       |
| Limitar tamanho de payload (áudio e logs)                             | V-03, V-04       | 1–2 horas        |
| Mover conversão de áudio para thread pool                             | P-02, P-03       | 1–2 horas        |
| Validações de modelo (EmailStr, Literal, max_length)                  | V-01, V-02       | 1 hora           |
| Migrar `class Config` para `model_config` (pydantic v2)               | A-05             | 30 minutos       |
| Remover duplicação `agent_id` e otimizar INSERT+RETURNING             | B-05, B-06, P-05 | 1 hora           |
| **Total estimado**                                                    |                  | **~7–12 horas**  |
