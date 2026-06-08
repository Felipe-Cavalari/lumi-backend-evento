# Relatório de Segurança — lumi-backend-evento

**Data:** 2026-06-08
**Escopo:** Aplicação FastAPI completa (`app/`), rotas, serviços, config, migrations e infra.

Há uma base de mitigações já feitas (parametrização SQL, `require_admin_key`, limite de
payload, sanitização de email), mas existem **falhas críticas em endpoints públicos**.

### Status de remediação (2026-06-08)

| ID | Severidade | Status |
|----|-----------|--------|
| C-01 | 🔴 Crítico | ✅ Resolvido |
| C-02 | 🔴 Crítico | ✅ Resolvido |
| A-01 | 🟠 Alto | ✅ Resolvido |
| A-02 | 🟠 Alto | ✅ Resolvido |
| A-03 | 🟠 Alto | ✅ Resolvido |
| M-01..M-04 | 🟡 Médio | ⬜ Pendente |
| B-01..B-03 | 🟢 Baixo | ⬜ Pendente |

---

## 🔴 CRÍTICO

### C-01 — Escrita de arquivo arbitrária (Path Traversal) via `speaker` — ✅ RESOLVIDO

**Arquivo:** `app/routes/transcripts.py` — `POST /api/transcripts/tts` e `POST /api/transcripts/stt`

Ambos os endpoints são **públicos** (sem `require_admin_key`). O campo `speaker` entrava cru
no nome do arquivo:

```python
filename = f"{safe_timestamp}_{audio.speaker}_{event_id}.{incoming_format}"
filepath = audio_dir / filename
```

O `lead_email` é sanitizado, mas `speaker` **não**. Escape do diretório confirmado:

```
speaker = "../../../../../../tmp/pwned"
→ resolved: /tmp/tmp/pwned_0.webm   (escapou de data/audio/lead/user_audio)
```

**Impacto:** atacante anônimo escreve arquivos em qualquer lugar gravável pelo processo, com
conteúdo arbitrário (bytes decodificados do base64) e extensão de `{webm,ogg,wav,mp3,m4a}`.
Pode sobrescrever arquivos, criar `.py`/configs em paths conhecidos, etc. O `/stt` tem o mesmo
problema (extensão fixa `.txt`, mas ainda permite traversal de diretório + conteúdo controlado).

**Correção:** sanitizar `speaker` (whitelist `{"user","agent"}`) e validar que
`filepath.resolve()` está dentro de `AUDIO_DIR.resolve()` / `TRANSCRIPTS_DIR.resolve()`.

**✅ Aplicado (2026-06-08):** correção em duas camadas:

1. **Whitelist no modelo:** `field_validator` em `TranscriptData` e `AudioData` (`_validate_speaker`)
   normaliza e exige `speaker ∈ {"user","agent"}`. Qualquer outro valor → `422` antes de
   qualquer I/O. Isso elimina o vetor de traversal na origem.
2. **Contenção de path (defesa em profundidade):** helper `_ensure_within(base, target)`
   resolve o caminho final e rejeita (`400`) se ele escapar de `TRANSCRIPTS_DIR` / `AUDIO_DIR`.
   Aplicado nos 3 pontos de montagem do `filepath` (stt, tts passthrough, tts conversão).
   Adicionado `except HTTPException: raise` no handler do `/stt` para o `400` não virar `500`.

Verificado: `speaker="../../../../tmp/pwned"` → `422` e **nenhum** arquivo criado fora do
diretório de dados; `speaker="agent"` segue salvando normalmente (`200`).

### C-02 — Endpoints de token ElevenLabs abusam da API key do servidor — ✅ RESOLVIDO

**Arquivo:** `app/routes/elevenlabs.py` — `POST /api/token/realtime-scribe`,
`GET /api/conversation/signed-url`, `GET /api/conversation/token`

Públicos e faziam fallback para a chave do servidor, aceitando inclusive um `Authorization`
arbitrário do cliente como `xi-api-key`:

```python
api_key = authorization.replace("Bearer ", "") if authorization else settings.elevenlabs_api_key
```

**Impacto:** qualquer pessoa na internet gerava tokens/signed-URLs **às custas da conta
ElevenLabs** (abuso financeiro / esgotamento de quota). Maior impacto monetário.

**Correção:** exigir autenticação (admin key ou sessão) e/ou rate limiting antes do fallback
para a chave do servidor.

**✅ Aplicado (2026-06-08):** modelo de acesso definido como **widget público anônimo**
(usuários finais no evento, sem login) — autenticação por `X-Admin-Key` não é viável (vazaria
a chave no frontend). Endurecimento em três camadas:

1. **Removido o fallback de `Authorization`:** os endpoints agora usam **sempre** a
   `ELEVENLABS_API_KEY` do servidor; o cliente não pode mais injetar credencial via header
   (eliminado o confused-deputy). Parâmetro `authorization` e imports `Header`/`Optional`
   removidos. Sem chave no servidor → `503`.
2. **Rate limit por IP:** `30/minute` em cada endpoint (ver A-03).
3. **Teto de uso GLOBAL:** `_enforce_global_token_quota()` — contador de janela fixa (1h) em
   memória limitando o total de gerações a `_TOKEN_QUOTA_MAX` (2000/h, ajustável). Protege a
   quota da conta contra abuso **distribuído** (muitos IPs), que o rate limit por IP não cobre.
   Excedente → `429`. *Nota:* contador é por processo; para multi-instância migrar para Redis
   (o módulo `app/cache.py` já está preparado para essa troca).

Verificado: import OK, suíte de testes passa (22/22), e o teto global retorna `429` após o
limite. Rate limit por IP validado em A-03.

---

## 🟠 ALTO

### A-01 — Endpoints de billing públicos (information disclosure) — ✅ RESOLVIDO

**Arquivo:** `app/routes/usage_twilio.py`, `app/routes/usage_elevenlabs.py`

`GET /api/usage/twilio` e `GET /api/usage/elevenlabs` não tinham `require_admin_key`. Expunham
**saldo da conta Twilio**, custos e uso/limite ElevenLabs a qualquer um. Cada chamada consumia
a API upstream (sem cache na primeira req → amplificação).

**Correção:** adicionar `dependencies=[Depends(require_admin_key)]`.

**✅ Aplicado (2026-06-08):** ambas as rotas agora declaram
`dependencies=[Depends(require_admin_key)]` no decorator, exigindo o header `X-Admin-Key`
(mesmo padrão das rotas protegidas de `leads.py`). Sem chave válida → `401`; com
`ADMIN_API_KEY` não configurado no servidor → `503`. Importados `Depends` e
`require_admin_key` em cada arquivo. Nenhuma alteração na lógica de negócio.

### A-02 — Escrita de logs sem autenticação → DoS por disco e log injection — ✅ RESOLVIDO

**Arquivo:** `app/routes/debug_logs.py` — `POST /api/debug/browser-logs`

Público. `message` não tinha limite de tamanho nem quantidade de `entries`, gravando direto em
disco. Vetor de enchimento de disco (DoS) e injeção de conteúdo em arquivos de log.

**Correção:** autenticar, limitar tamanho/quantidade, rate limit.

**✅ Aplicado (2026-06-08):**

- **Bounds de payload via Pydantic `Field`:** `message` ≤ 10.000 chars, `level` ≤ 20,
  `session_id` ≤ 200, `lead_email` ≤ 320, e **máximo de 500 `entries` por requisição**.
  Payloads acima do limite são rejeitados com `422` antes de tocar o disco.
- **Rate limit** de `30/minute` por IP (ver A-03).
- **Autenticação intencionalmente NÃO aplicada:** o endpoint é chamado pelo browser do
  usuário final para capturar logs de console; exigir `X-Admin-Key` exporia a chave no
  frontend e quebraria o recurso. Para um endpoint inerentemente público, a mitigação correta
  é bound de payload + rate limit, e não autenticação.

Verificado: 30 requisições passam e a 31ª retorna `429`; `entries > 500` e `message > 10k`
retornam `422`.

### A-03 — Ausência total de rate limiting — ✅ RESOLVIDO

Nenhum endpoint tinha rate limiting. Combinado com `POST /api/leads/register` (público), os
endpoints de escrita de arquivo (C-01) e de token (C-02), permitia spam de leads, esgotamento
de disco e abuso de quota.

**Correção:** middleware de rate limiting (ex. `slowapi`) global e mais restrito nos endpoints
públicos de escrita.

**✅ Aplicado (2026-06-08):** adicionado `slowapi` (`requirements.txt`).

- **Novo módulo `app/rate_limit.py`** com uma instância única de `Limiter` compartilhada. A
  chave do cliente usa `X-Forwarded-For` (primeiro IP) quando presente, com fallback para o IP
  da conexão — correto atrás do proxy reverso (Coolify/Docker), que de outro modo agruparia
  todos os clientes no IP do proxy.
- **`app/main.py`:** registra `app.state.limiter` e o handler de `RateLimitExceeded` (responde
  `429`).
- **Limites por rota** (decorator `@limiter.limit`) nos endpoints públicos:
  - `POST /api/leads/register` → **20/min** (anti-spam de leads)
  - `POST /api/transcripts/stt` e `/tts` → **300/min** (generoso de propósito, para não
    estrangular o stream de transcrição/áudio durante chamadas ativas)
  - `POST /api/token/realtime-scribe`, `GET /api/conversation/signed-url`,
    `GET /api/conversation/token` → **30/min** (mitiga parcialmente o abuso da chave do
    servidor descrito em C-02)
  - `POST /api/debug/browser-logs` → **30/min**
- **Decisão de design:** optou-se por limites **por rota** em vez de um `default_limits`
  global, justamente para não impor um teto único que poderia derrubar o fluxo de transcrição
  em tempo real. As rotas administrativas (`leads` CRUD, deletes, usage) já são protegidas por
  `X-Admin-Key`. Decisão documentada em `app/rate_limit.py`.

Verificado: requisições além do limite retornam `429`; suíte de testes existente passa (22/22).

---

## 🟡 MÉDIO

### M-01 — Vazamento de detalhes internos em mensagens de erro

Vários handlers retornam detalhes upstream/internos ao cliente:

- `elevenlabs.py`: `detail=f"...{e.response.text}"` e `detail=f"...{data}"` (pode conter dados
  sensíveis da ElevenLabs).
- `transcripts.py` / `debug_logs.py`: `detail=f"...{str(e)}"` (exceções internas).

`leads.py` e os health checks já fazem certo (logam internamente, retornam genérico).
Padronizar nos demais.

### M-02 — Comparação de admin key não é constant-time

**Arquivo:** `app/security.py` — `if x_admin_key != settings.admin_api_key` é vulnerável a
timing attack.

**Correção:** `secrets.compare_digest(x_admin_key or "", settings.admin_api_key)`.

### M-03 — Log de signed URLs / tokens

**Arquivo:** `app/routes/elevenlabs.py` loga `response.text[:500]` e o `data` completo, que
contêm signed URLs/tokens (credenciais de curta duração). Quem tiver acesso aos logs obtém
esses segredos.

**Correção:** não logar corpo de respostas que contêm tokens.

### M-04 — CORS com `allow_credentials=True` + `allow_headers=["*"]`/`expose_headers=["*"]`

**Arquivo:** `app/main.py`. O default de origin é seguro (localhost), mas se `CORS_ORIGINS`
for configurado com `*` em produção, combinado com credenciais, vira CSRF/leak. Garantir que
a env nunca use wildcard e restringir headers expostos.

---

## 🟢 BAIXO / Observações

- **B-01** — `app/database.py` usa `ssl=False`. Justificado por rede interna Docker, mas
  documentar o requisito; se o Postgres ficar acessível fora da rede interna, vira MITM.
- **B-02** — `base64.b64decode(audio.audio_base64)` sem `validate=True` (aceita lixo
  silenciosamente). Cosmético.
- **B-03** — `datetime.utcnow()` (deprecado no 3.12+) — não é segurança.

---

## ✅ O que está correto

- **Sem SQL injection**: todas as queries usam placeholders (`$1`...). O
  `PATCH /api/leads/{id}` monta SQL dinâmico, mas os nomes de coluna vêm dos campos fixos do
  modelo Pydantic `LeadPatch` — não são controláveis pelo cliente. Valores parametrizados.
  **Seguro.**
- Validação de UUID antes de query.
- `.env` no `.gitignore`, sem segredos commitados (só `.env.example` com placeholders).
- Limite de 20 MB no payload de áudio (mitiga parte do DoS).

---

## Prioridade de correção

1. **C-01** e **C-02** — exploráveis anonimamente, alto impacto.
2. **A-01 / A-02 / A-03** — autenticação + rate limiting nos endpoints públicos.
3. **M-01 a M-04** — hardening.
