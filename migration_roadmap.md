# 🗺️ Roadmap — Migração Supabase → PostgreSQL (Coolify, mesma VPS, asyncpg)

> **Data:** 2026-06-02
> **Alvo:** PostgreSQL self-hosted via **Coolify**, na **mesma VPS** do backend
> **Stack de acesso:** **asyncpg puro** + **Alembic** (migrações)
> **Escopo real:** 1 tabela (`leads`) + 2 arquivos (`database.py`, `leads.py`)

---

## 0. Reality check (leia antes de começar)

- **Supabase já é Postgres.** Os timeouts atuais (`select 1` falhando) são quase certamente **free-tier pausando** ou **modo de conexão errado** (direct vs pooler) — não o Postgres em si. Os commits recentes ("transaction pool ao invés de direct connection", "troca de lib") confirmam essa luta.
- **Ganho de segurança real desta migração:** hoje o app usa o cliente Supabase (**PostgREST sobre HTTP + chave anon**), o que mantém uma **API REST pública de dados** como superfície de ataque (item M-09 do `security_review_02_06.md`). Postgres privado atrás do backend, com queries parametrizadas, **elimina essa superfície pública inteira**. ✅
- **Perda de segurança a compensar:** você **abre mão do RLS** como camada de defesa. Portanto os fixes de auth da aplicação (**C-01, C-02, H-01** do relatório) ficam **ainda mais críticos** depois da migração. O Postgres só protege os dados se o backend protege os endpoints.
- ⚠️ **Caveat de estabilidade (mesma VPS):** colocar Postgres no mesmo host do app **reduz isolamento** — se a VPS cair, app e banco caem juntos; e a conversão de áudio CPU-bound (**H-06**) compete por CPU/RAM com o banco. Isso é o oposto de "mais estável" se a VPS for pequena. **Mitigação obrigatória:** definir **limites de CPU/memória** nos containers (Fase 5) e ter **backups offsite** (Fase 6).

**Esforço total estimado: ~3–4 dias.** Volume de dados é trivial; o trabalho é a reescrita + validação.

---

## Fase 1 — Provisionar Postgres no Coolify (½ dia)

1. **Coolify → Databases → + New → PostgreSQL** (versão **16** ou **17**). Mesmo *Project* do backend para compartilhar a rede interna Docker.
2. **NÃO** habilitar "Public Port" / "Make publicly available". O banco fica acessível **só pela rede interna do Docker** — essa é a principal vantagem de segurança.
3. Coolify gera a credencial e duas URLs:
   - **Internal** → `postgresql://postgres:<senha>@<service-name>:5432/postgres` ← **use esta**.
   - Public → ignorar/deixar desabilitada.
4. Criar um **usuário de aplicação dedicado** (não usar o superuser `postgres` no app):
   ```sql
   create user lumi_app with password '<senha-forte>';
   create database lumi;
   grant connect on database lumi to lumi_app;
   -- após criar o schema (Fase 2):
   grant select, insert, update on leads to lumi_app;
   -- sem delete (as rotas de delete são de arquivos, não de leads)
   ```
5. Anotar a connection string **interna** com o usuário `lumi_app` para usar como `DATABASE_URL`.

---

## Fase 2 — Schema versionado com Alembic (½ dia)

1. `requirements.txt`: **adicionar** `asyncpg`, `alembic`, `sqlalchemy>=2.0` (Alembic precisa do SQLAlchemy só p/ migração); **remover** `supabase`.
2. `alembic init migrations` e apontar `sqlalchemy.url` para a `DATABASE_URL` (via env, **não** hardcoded).
3. Migration inicial da `leads` (espelha o schema atual, com melhorias):
   ```sql
   create table leads (
       id                          uuid primary key default gen_random_uuid(),
       created_at                  timestamptz not null default now(),
       nome                        text not null,
       contato                     text not null unique,         -- dedup atômico
       empresa                     text,
       contato_feito               boolean not null default false,
       elevenlabs_conversation_id  text
   );
   create index idx_leads_contato on leads(contato);
   ```
   > `contato unique` resolve a corrida do dedup atual (`leads.py:35-41`) no nível do banco.
4. Aplicar: `alembic upgrade head`.

---

## Fase 3 — Reescrever a camada de dados em asyncpg (1 dia)

### 3.1 `app/config.py`
- **Adicionar** `database_url: str = Field(..., alias="DATABASE_URL")`.
- **Remover** `supabase_url` / `supabase_key`.
- (Ao migrar o config, aproveitar para trocar `class Config` por `model_config = SettingsConfigDict(...)` — item A-05.)

### 3.2 `app/database.py` (reescrita completa — pool asyncpg)
```python
"""Pool de conexões PostgreSQL (asyncpg)."""
import asyncpg
from app.config import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    if _pool is None:
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
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Pool de banco não inicializado")
    return _pool
```

### 3.3 `app/main.py` — conectar no lifespan (hoje vazio em `main.py:15-17`)
```python
from app.database import init_pool, close_pool

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()
```
E atualizar `/api/health` (`main.py:60`) para `await get_pool().fetchval("select 1")` — **sem** devolver `str(e)` ao cliente (item M-01).

### 3.4 `app/routes/leads.py` — PostgREST → SQL parametrizado
> Parametrização (`$1, $2, ...`) = **imune a SQL injection**. Exemplos:

**register** (atômico, sem o INSERT+SELECT redundante — P-05/B-06):
```python
pool = get_pool()
row = await pool.fetchrow(
    """insert into leads (nome, contato, empresa, contato_feito, elevenlabs_conversation_id)
       values ($1, $2, $3, coalesce($4, false), $5)
       on conflict (contato) do update set contato = leads.contato
       returning id""",
    lead.nome, lead.contato, lead.empresa, lead.contato_feito,
    lead.elevenlabs_conversation_id,
)
return {"success": True, "lead_id": str(row["id"])}
```

**list** (`leads.py:70`):
```python
rows = await pool.fetch(
    """select id, created_at, nome, contato, empresa, contato_feito,
              elevenlabs_conversation_id
       from leads order by created_at desc"""
)
```

**by-contato** (`leads.py:97`):
```python
row = await pool.fetchrow("select ... from leads where contato = $1", contato)
```

**patch empresa / contato-feito** (`leads.py:134,154`):
```python
row = await pool.fetchrow(
    "update leads set empresa = $1 where id = $2 returning id", body.empresa, lead_id
)
if row is None:
    raise HTTPException(status_code=404, detail="Lead não encontrado.")
```
> Substituir todos os `if not settings.supabase_url` por checagens de pool. Manter `dependencies=[Depends(require_admin_key)]` nas rotas admin.

---

## Fase 4 — Migração dos dados do Supabase (½ dia)

1. **Exportar** do Supabase (SQL Editor, que usa conexão direta e não depende do MCP):
   ```sql
   copy (select * from leads) to stdout with csv header;
   ```
   ou `pg_dump --data-only --table=leads "<conn-supabase>" > leads.sql`.
2. **Importar** no Postgres do Coolify (via rede interna ou túnel temporário):
   ```bash
   psql "<DATABASE_URL>" -c "\copy leads from 'leads.csv' with csv header"
   ```
3. **Validar:** comparar `select count(*)` nos dois lados + amostragem de alguns registros antes do cutover.

---

## Fase 5 — Limites de recursos & segurança (½ dia) — *crítico no cenário mesma-VPS*

- **Limites de CPU/memória** nos containers (Coolify → Resource Limits) para o Postgres e o backend, evitando que a conversão de áudio (H-06) sufoque o banco. Ex.: reservar RAM mínima ao Postgres.
- **Segredos:** `DATABASE_URL` como **Environment Variable** do app no Coolify (marcar como secret). Nunca versionar — o `.env` já está no `.gitignore`; manter assim.
- **Rede:** confirmar que a porta do Postgres **não** está publicada na internet (só rede interna Docker).
- **Usuário mínimo:** app conecta como `lumi_app` (sem superuser, sem `delete`).
- `tune` básico do Postgres conforme RAM da VPS (`shared_buffers`, `max_connections` alinhado ao `max_size=10` do pool).

---

## Fase 6 — Backups & monitoring (½ dia) — *obrigatório*

- **Coolify → seu Postgres → Backups:** habilitar backup agendado (diário), retenção, e **destino S3/offsite** (não só local — se a VPS morrer, o backup local morre junto).
- **Testar um restore** num banco descartável antes de confiar.
- Monitorar disco da VPS (backups + `data/` de áudios podem encher o disco — ver H-01).
- `pg_stat_statements` para queries lentas (opcional).

---

## Fase 7 — Cutover & rollback (½ dia)

1. Deploy em **staging/preview** com a nova `DATABASE_URL`; rodar smoke test: `register → list → by-contato → patch`.
2. Janela curta (tabela pequena): freeze de writes → export final → import → trocar a `DATABASE_URL` de produção → redeploy no Coolify.
3. **Rollback:** manter o Supabase **ligado e intacto por ~1 semana**; reverter = só voltar a env var. (Por isso a remoção do código Supabase fica na Fase 8, depois de validar.)

---

## Fase 8 — Decomissionar Supabase (após validação)

- Remover `supabase` de `requirements.txt`, o server do `.mcp.json`, e `SUPABASE_*` do config.
- Revogar as chaves Supabase; pausar/excluir o projeto.
- Atualizar `PROJECT.md` e marcar **M-09 como resolvido** no `security_review_02_06.md` (PostgREST público + ambiguidade de RLS deixam de existir).

---

## Checklist de arquivos

| Arquivo | Mudança |
|---|---|
| `requirements.txt` | `+asyncpg, +alembic, +sqlalchemy`; `−supabase` |
| `app/config.py` | `+database_url`; remover `supabase_*`; migrar p/ `model_config` |
| `app/database.py` | pool asyncpg (reescrita completa) |
| `app/main.py` | `init_pool`/`close_pool` no lifespan; `/api/health` sem `str(e)` |
| `app/routes/leads.py` | SQL parametrizado (5 queries) |
| `migrations/` | Alembic (novo) |
| `Dockerfile` | nenhuma mudança (asyncpg é wheel) |
| `.mcp.json` | remover server supabase (Fase 8) |
| Coolify | Postgres interno + limites + backups |

---

## ⚠️ Lembrete de segurança (não esquecer)

Esta migração **não** corrige a falha principal do sistema. Depois de migrar, **priorizar os itens do `security_review_02_06.md`**:
- **C-01 / C-02** — autenticar `/api/token/*`, `/api/conversation/*`, `/api/usage/*`.
- **H-01** — autenticar/limitar as rotas que escrevem em disco (`/stt`, `/tts`, `/browser-logs`, `/leads/register`).
- **H-04** — rate limiting global.

Sem RLS para te proteger, o banco fica **inteiramente** dependente da auth da aplicação.
