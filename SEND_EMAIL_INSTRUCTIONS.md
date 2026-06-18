# 📧 Envio de E-mail por SMTP em Python (FastAPI) — Guia Reaproveitável

Guia completo e autocontido para adicionar **envio de e-mail de notificação via SMTP**
a um projeto Python — usando apenas a **biblioteca padrão** (`smtplib` + `email`),
sem dependências externas. Inclui template **HTML** bonito, integração assíncrona
com FastAPI, configuração via `.env` e prompts prontos para agentes de IA.

> Este documento foi extraído de uma feature real ("notificar por e-mail quando um
> cliente inicia uma conversa") e generalizado para servir de base em outros projetos.

---

## 📑 Índice

1. [Visão geral](#1-visão-geral)
2. [Por que `smtplib` da stdlib](#2-por-que-smtplib-da-stdlib)
3. [Configuração (variáveis de ambiente)](#3-configuração-variáveis-de-ambiente)
4. [Camada de configuração (Pydantic Settings)](#4-camada-de-configuração-pydantic-settings)
5. [O serviço de e-mail completo](#5-o-serviço-de-e-mail-completo)
6. [Template HTML (com exemplo renderizado)](#6-template-html-com-exemplo-renderizado)
7. [Como disparar o envio (integração)](#7-como-disparar-o-envio-integração)
8. [Como testar](#8-como-testar)
9. [Gmail / provedores: senha de app e portas](#9-gmail--provedores-senha-de-app-e-portas)
10. [Boas práticas e armadilhas comuns](#10-boas-práticas-e-armadilhas-comuns)
11. [Checklist de implementação](#11-checklist-de-implementação)
12. [Prompts prontos para agentes de IA](#12-prompts-prontos-para-agentes-de-ia)

---

## 1. Visão geral

A feature envia um e-mail (HTML + texto puro de fallback) quando um evento de negócio
acontece (ex.: novo lead, nova conversa, novo pedido). Princípios de design:

- **Sem dependências novas**: usa `smtplib` e `email.message.EmailMessage` da stdlib.
- **Não bloqueia o event loop**: o envio SMTP é síncrono, então roda em uma thread
  via `asyncio.to_thread(...)`.
- **Best-effort**: uma falha no envio é **logada**, mas **nunca** quebra a operação
  principal (o registro do dado de negócio).
- **Configurável e desativável**: se as variáveis SMTP não estiverem preenchidas, o
  envio é silenciosamente ignorado (útil em dev/CI).
- **Multipart**: envia `text/plain` (fallback) + `text/html` (visual bonito).

Fluxo:

```
[Evento de negócio]  ──►  send_notification(dados)
                              │
                              ├─ SMTP configurado? ── não ──►  log e retorna (no-op)
                              │
                              └─ sim ─► monta EmailMessage (texto + HTML)
                                        └─ asyncio.to_thread(_send_sync)
                                            └─ smtplib.SMTP → STARTTLS → login → send
```

---

## 2. Por que `smtplib` da stdlib

| Abordagem | Prós | Contras |
|-----------|------|---------|
| **`smtplib` (stdlib)** ✅ | Zero dependências; estável; total controle | É síncrona (resolvido com `to_thread`) |
| `aiosmtplib` | Async nativo | Dependência extra |
| SDK de provedor (SendGrid, SES) | Métricas, deliverability | Lock-in, API key, dependência |

Para notificações internas de baixo volume, **`smtplib` é a escolha mais simples e
portável**. Para alto volume / e-mail transacional em produção, considere um provedor
dedicado (SES, SendGrid, Resend, Postmark).

---

## 3. Configuração (variáveis de ambiente)

Adicione ao seu `.env` (e documente no `.env.example`):

```dotenv
# SMTP - envio de e-mail de notificação.
# A notificação só dispara quando SMTP_HOST e NOTIFICATION_EMAIL estão definidos.
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=seu_email@gmail.com
SMTP_PASSWORD=sua_senha_de_app
SMTP_FROM=seu_email@gmail.com
SMTP_USE_TLS=true
# Destinatário que recebe o aviso
NOTIFICATION_EMAIL=destino@empresa.com
```

| Variável | Obrigatória | Default | Descrição |
|----------|-------------|---------|-----------|
| `SMTP_HOST` | Sim (p/ ativar) | — | Host do servidor SMTP (ex.: `smtp.gmail.com`) |
| `SMTP_PORT` | Não | `587` | Porta. `587` = STARTTLS, `465` = SSL puro |
| `SMTP_USER` | Não* | — | Usuário de autenticação |
| `SMTP_PASSWORD` | Não* | — | Senha (no Gmail, **senha de app**) |
| `SMTP_FROM` | Não | cai p/ `SMTP_USER` | Remetente exibido |
| `SMTP_USE_TLS` | Não | `true` | Usa STARTTLS na porta 587 |
| `NOTIFICATION_EMAIL` | Sim (p/ ativar) | — | Destinatário da notificação |

\* Servidores SMTP autenticados exigem usuário/senha. Relays internos podem dispensar.

---

## 4. Camada de configuração (Pydantic Settings)

Usando `pydantic-settings` (padrão em projetos FastAPI modernos):

```python
"""app/config.py — configurações da aplicação."""
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"


class Settings(BaseSettings):
    # ... outras configs do projeto ...

    # SMTP — notificação por e-mail.
    smtp_host: Optional[str] = Field(None, alias="SMTP_HOST")
    smtp_port: int = Field(587, alias="SMTP_PORT")
    smtp_user: Optional[str] = Field(None, alias="SMTP_USER")
    smtp_password: Optional[str] = Field(None, alias="SMTP_PASSWORD")
    smtp_from: Optional[str] = Field(None, alias="SMTP_FROM")
    smtp_use_tls: bool = Field(True, alias="SMTP_USE_TLS")
    notification_email: Optional[str] = Field(None, alias="NOTIFICATION_EMAIL")

    @property
    def smtp_from_value(self) -> str:
        """Remetente; cai para o usuário SMTP se SMTP_FROM não for definido."""
        return self.smtp_from or self.smtp_user or ""

    @property
    def smtp_configured(self) -> bool:
        """True quando há host SMTP e destinatário configurados."""
        return bool(self.smtp_host and self.notification_email)

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        case_sensitive=False,
        populate_by_name=True,
        extra="ignore",
    )


settings = Settings()
```

> **Sem Pydantic?** Troque por `os.getenv("SMTP_HOST")` etc. e uma função
> `smtp_configured()` que checa `host` e destinatário.

---

## 5. O serviço de e-mail completo

Arquivo `app/services/email_service.py`. **Copiável quase sem alterações** — só ajuste
os campos do payload e os textos.

```python
"""Envio de e-mail de notificação via SMTP."""
import asyncio
import logging
import smtplib
from email.message import EmailMessage
from html import escape

from app.config import settings

logger = logging.getLogger(__name__)

_ACCENT = "#2563eb"  # cor de destaque do template (azul)


def _text_body(data: dict) -> str:
    """Versão texto puro — fallback para clientes que não renderizam HTML."""
    return (
        "Uma nova notificação foi gerada.\n\n"
        f"Nome: {data.get('nome') or '(sem nome)'}\n"
        f"Contato: {data.get('contato') or '(sem contato)'}\n"
        f"ID: {data.get('id') or '(não informado)'}\n"
    )


def _html_body(data: dict) -> str:
    """Versão HTML — todos os estilos são INLINE (exigência de clientes de e-mail)."""
    nome = escape(data.get("nome") or "(sem nome)")
    contato = escape(data.get("contato") or "(sem contato)")
    item_id = escape(data.get("id") or "(não informado)")

    def row(rotulo: str, valor: str) -> str:
        return (
            '<tr>'
            f'<td style="padding:10px 16px;color:#6b7280;font-size:13px;'
            f'border-bottom:1px solid #f0f0f0;white-space:nowrap;">{rotulo}</td>'
            f'<td style="padding:10px 16px;color:#111827;font-size:15px;'
            f'font-weight:600;border-bottom:1px solid #f0f0f0;">{valor}</td>'
            '</tr>'
        )

    return f"""\
<!DOCTYPE html>
<html lang="pt-BR">
<body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);">
          <tr>
            <td style="background:{_ACCENT};padding:24px 28px;">
              <div style="display:inline-block;background:rgba(255,255,255,0.18);color:#ffffff;font-size:12px;font-weight:600;letter-spacing:0.5px;text-transform:uppercase;padding:4px 10px;border-radius:999px;">Notificação</div>
              <h1 style="margin:12px 0 0;color:#ffffff;font-size:22px;font-weight:700;">Novo evento recebido 🎉</h1>
              <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:14px;">Veja abaixo os detalhes do evento.</p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 28px 8px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #f0f0f0;border-radius:8px;overflow:hidden;">
                {row("Nome", nome)}
                {row("Contato", contato)}
                {row("ID", item_id)}
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 28px 28px;">
              <p style="margin:0;color:#9ca3af;font-size:12px;line-height:1.5;">
                Este e-mail foi enviado automaticamente pelo backend.<br>
                Você está recebendo porque foi configurado como destinatário das notificações.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _build_message(data: dict) -> EmailMessage:
    nome = data.get("nome") or "(sem nome)"
    msg = EmailMessage()
    msg["Subject"] = f"Nova notificação: {nome}"
    msg["From"] = settings.smtp_from_value
    msg["To"] = settings.notification_email
    msg.set_content(_text_body(data))            # fallback texto puro
    msg.add_alternative(_html_body(data), subtype="html")  # versão HTML
    return msg


def _send_sync(msg: EmailMessage) -> None:
    """Envio BLOQUEANTE — chamado via asyncio.to_thread para não travar o event loop."""
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_user and settings.smtp_password:
            # Senhas de app do Google são exibidas com espaços; .strip() evita falha de login.
            server.login(settings.smtp_user, settings.smtp_password.strip())
        server.send_message(msg)


async def send_notification(data: dict) -> None:
    """Envia (best-effort) o e-mail de notificação.

    Falhas são apenas logadas — nunca devem quebrar a operação principal.
    """
    if not settings.smtp_configured:
        logger.info("SMTP não configurado; e-mail de notificação ignorado.")
        return
    try:
        msg = _build_message(data)
        await asyncio.to_thread(_send_sync, msg)
        logger.info("E-mail de notificação enviado para %s", settings.notification_email)
    except Exception:
        logger.exception("Falha ao enviar e-mail de notificação")
```

### Versão para porta 465 (SSL puro)

Se o provedor usar SSL puro (porta 465) em vez de STARTTLS (587), troque `_send_sync`:

```python
def _send_sync(msg: EmailMessage) -> None:
    if settings.smtp_use_tls:  # interprete "use_tls" como SSL implícito aqui
        server_cm = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15)
    else:
        server_cm = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
    with server_cm as server:
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password.strip())
        server.send_message(msg)
```

### Versão pura (sem FastAPI / sem Pydantic)

Para um script simples, sem `settings`:

```python
import os, smtplib
from email.message import EmailMessage

def send_email(subject: str, html: str, text: str, to: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ["SMTP_FROM"]
    msg["To"] = to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587"))) as s:
        s.starttls()
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"].strip())
        s.send_message(msg)
```

---

## 6. Template HTML (com exemplo renderizado)

O HTML usa **estilos inline** porque a maioria dos clientes de e-mail (Gmail, Outlook)
**ignora `<style>` e CSS externo**. Layout baseado em `<table>` pelo mesmo motivo
(compatibilidade máxima). Estrutura:

```
┌──────────────────────────────────────┐
│  [BADGE]  ← faixa colorida (header)    │
│  Título grande 🎉                      │
│  Subtítulo                             │
├──────────────────────────────────────┤
│  Nome      │  João da Silva            │  ← tabela de dados
│  Contato   │  5511999998888            │
│  ID        │  abc-123                  │
├──────────────────────────────────────┤
│  rodapé discreto (cinza)               │
└──────────────────────────────────────┘
```

Exemplo de HTML final gerado (com `nome="João da Silva"`, `contato="5511999998888"`,
`id="conv_abc123"`):

```html
<!DOCTYPE html>
<html lang="pt-BR">
<body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);">
          <tr>
            <td style="background:#2563eb;padding:24px 28px;">
              <div style="display:inline-block;background:rgba(255,255,255,0.18);color:#ffffff;font-size:12px;font-weight:600;letter-spacing:0.5px;text-transform:uppercase;padding:4px 10px;border-radius:999px;">Notificação</div>
              <h1 style="margin:12px 0 0;color:#ffffff;font-size:22px;font-weight:700;">Novo evento recebido 🎉</h1>
              <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:14px;">Veja abaixo os detalhes do evento.</p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 28px 8px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #f0f0f0;border-radius:8px;overflow:hidden;">
                <tr>
                  <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f0f0f0;white-space:nowrap;">Nome</td>
                  <td style="padding:10px 16px;color:#111827;font-size:15px;font-weight:600;border-bottom:1px solid #f0f0f0;">João da Silva</td>
                </tr>
                <tr>
                  <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f0f0f0;white-space:nowrap;">Contato</td>
                  <td style="padding:10px 16px;color:#111827;font-size:15px;font-weight:600;border-bottom:1px solid #f0f0f0;">5511999998888</td>
                </tr>
                <tr>
                  <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f0f0f0;white-space:nowrap;">ID</td>
                  <td style="padding:10px 16px;color:#111827;font-size:15px;font-weight:600;border-bottom:1px solid #f0f0f0;">conv_abc123</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 28px 28px;">
              <p style="margin:0;color:#9ca3af;font-size:12px;line-height:1.5;">
                Este e-mail foi enviado automaticamente pelo backend.<br>
                Você está recebendo porque foi configurado como destinatário das notificações.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
```

> 💡 **Personalização rápida**: mude `_ACCENT` para a cor da marca, troque o emoji/título
> no header, e adicione/remova linhas chamando `row("Rótulo", valor)`.
> 🔒 **Sempre** passe valores dinâmicos por `html.escape(...)` para evitar quebra de
> layout / injeção de HTML.

---

## 7. Como disparar o envio (integração)

Chame `send_notification(...)` no ponto exato do evento de negócio. Em FastAPI, basta
`await` (a função já é não-bloqueante internamente e engole os próprios erros).

```python
from app.services.email_service import send_notification

@router.post("/register")
async def register(item: ItemCreate):
    row = await repo.insert(item)        # operação principal
    await send_notification({            # notificação (best-effort)
        "nome": item.nome,
        "contato": item.contato,
        "id": str(row["id"]),
    })
    return {"success": True, "id": str(row["id"])}
```

### Dica: disparar só quando uma condição é satisfeita

No projeto original, o e-mail só deve sair quando um campo específico é preenchido
(ex.: o cliente "iniciou a conversa", marcado por um `conversation_id`). Padrão útil
para **evitar e-mail duplicado** — só notifica quando o valor **muda**:

```python
new_value = changes.get("conversation_id")
prev_value = None
if new_value:
    prev_value = await repo.get_field(item_id, "conversation_id")  # valor atual
row = await repo.update(item_id, changes)
if new_value and new_value != prev_value:   # mudou → é um evento novo
    await send_notification({...})
```

> ⚠️ **Onde colocar o gatilho importa.** No projeto real o ID só existia em um `PATCH`
> posterior (não no `POST` inicial). Confirme **em qual requisição** o dado que você
> precisa realmente chega — um log temporário no handler resolve a dúvida rápido.

### Alternativa: não esperar o envio (fire-and-forget)

Se não quiser nem o pequeno custo do `to_thread` no caminho da resposta, dispare em
background com `BackgroundTasks` do FastAPI:

```python
from fastapi import BackgroundTasks

@router.post("/register")
async def register(item: ItemCreate, background: BackgroundTasks):
    row = await repo.insert(item)
    background.add_task(send_notification, {"nome": item.nome, "id": str(row["id"])})
    return {"success": True}
```

---

## 8. Como testar

### Teste direto da função (sem servidor)

```bash
python -c "
import asyncio, logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
from app.services.email_service import send_notification
asyncio.run(send_notification({'nome':'Maria Teste','contato':'5511988887777','id':'abc-123'}))
"
```

Saída esperada: `INFO E-mail de notificação enviado para destino@empresa.com`
(uma exceção apareceria como `ERROR ...` — ausência de erro = sucesso).

### Teste do endpoint no servidor em execução

```bash
python -c "
import httpx
r = httpx.post('http://localhost:8000/api/register',
               json={'nome':'Teste','contato':'+5511999998888'}, timeout=30)
print(r.status_code, r.json())
"
```

### Inspecionar o HTML gerado sem enviar

```bash
python -c "
from app.services.email_service import _html_body
open('preview.html','w').write(_html_body({'nome':'João','contato':'5511999','id':'abc'}))
print('Abra preview.html no navegador')
"
```

### Teste automatizado com SMTP mockado (pytest)

```python
from unittest.mock import patch, MagicMock
import pytest
from app.services import email_service

@pytest.mark.asyncio
async def test_send_notification_calls_smtp(monkeypatch):
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(email_service.settings, "notification_email", "to@test.com")
    fake = MagicMock()
    with patch("smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = fake
        await email_service.send_notification({"nome": "X", "id": "1"})
    assert fake.send_message.called
```

---

## 9. Gmail / provedores: senha de app e portas

### Gmail (mais comum em projetos pequenos)

1. A conta precisa de **verificação em duas etapas (2FA)** ativada.
2. Gere uma **Senha de app**: https://myaccount.google.com/apppasswords
3. Use essa senha (16 caracteres, exibida com espaços) em `SMTP_PASSWORD`.
   - O Google ignora os espaços, mas faça `.strip()` por segurança (já incluído).
4. Config: `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USE_TLS=true`.

### Tabela de portas

| Porta | Modo | Como conectar |
|-------|------|---------------|
| **587** | STARTTLS (recomendado) | `smtplib.SMTP(...)` + `server.starttls()` |
| **465** | SSL/TLS implícito | `smtplib.SMTP_SSL(...)` (ver variante na seção 5) |
| 25 | Sem criptografia | Evite; bloqueada na maioria das redes |

### Outros provedores

| Provedor | Host | Porta |
|----------|------|-------|
| Gmail | `smtp.gmail.com` | 587 |
| Outlook/Office365 | `smtp.office365.com` | 587 |
| Amazon SES | `email-smtp.<região>.amazonaws.com` | 587 |
| SendGrid | `smtp.sendgrid.net` | 587 (user = `apikey`) |
| Zoho | `smtp.zoho.com` | 587 |

---

## 10. Boas práticas e armadilhas comuns

✅ **Faça:**
- Mantenha o envio **best-effort** (try/except que só loga) — notificação nunca deve
  derrubar a operação de negócio.
- Use `asyncio.to_thread` para não bloquear o event loop em código async.
- Sempre envie **multipart** (texto + HTML) para máxima compatibilidade.
- `html.escape()` em **todo** valor dinâmico interpolado no HTML.
- Deixe a feature **desativável** via config (`smtp_configured`).
- Estilos **inline** + layout em **tabela** no HTML.

❌ **Evite:**
- Commitar credenciais SMTP — mantenha no `.env` (que deve estar no `.gitignore`).
- Bloquear o event loop chamando `smtplib` direto em `async def` sem `to_thread`.
- `<style>` no `<head>` ou CSS externo — clientes de e-mail ignoram.
- Disparar o e-mail no handler errado — confirme onde o dado realmente chega.
- Reenviar e-mail em chamadas idempotentes/retries — guarde por mudança de estado.

⚠️ **Armadilhas comuns:**
- **Gatilho no lugar errado**: o dado esperado (ex.: um ID) pode chegar em uma
  requisição diferente da que você imagina. Use um log temporário para confirmar.
- **E-mail duplicado**: se a mesma operação roda mais de uma vez (retry do cliente),
  compare o valor novo com o anterior e só notifique se mudou.
- **Timeout/travamento**: sempre passe `timeout=` ao `smtplib.SMTP(...)`.
- **Caiu no spam**: configure SPF/DKIM no domínio; remetente igual à conta autenticada.

---

## 11. Checklist de implementação

- [ ] Adicionar variáveis SMTP ao `.env` e `.env.example`
- [ ] Adicionar campos SMTP + properties `smtp_from_value` / `smtp_configured` ao config
- [ ] Criar `app/services/email_service.py` (copiar da seção 5)
- [ ] Ajustar payload (`data`), assunto e linhas (`row(...)`) ao seu domínio
- [ ] Personalizar cor (`_ACCENT`), título e emoji do header
- [ ] Chamar `await send_notification(...)` no ponto certo do fluxo
- [ ] (Opcional) Guarda contra duplicata por mudança de estado
- [ ] Testar envio direto + via endpoint
- [ ] Configurar senha de app (Gmail) ou credenciais do provedor
- [ ] Confirmar recebimento (inclusive checar spam na 1ª vez)
- [ ] (Opcional) Teste pytest com SMTP mockado

---

## 12. Prompts prontos para agentes de IA

Cole um destes prompts no seu agente (Claude Code, Codex, Cursor, etc.) para replicar a
feature em outro projeto. **Ajuste os trechos entre `<...>`.**

### 🟣 Prompt curto (qualquer agente)

```
Adicione envio de e-mail de notificação via SMTP a este projeto Python, usando apenas
a biblioteca padrão (smtplib + email.message.EmailMessage), sem dependências novas.

Requisitos:
- Crie um serviço de e-mail assíncrono (envio síncrono rodando em asyncio.to_thread
  para não bloquear o event loop).
- Envie e-mail multipart: texto puro (fallback) + HTML com estilos INLINE e layout em
  tabela (compatível com Gmail/Outlook). Header colorido com badge, tabela de dados e
  rodapé discreto. Escape todo valor dinâmico com html.escape.
- Configure por variáveis de ambiente: SMTP_HOST, SMTP_PORT (default 587), SMTP_USER,
  SMTP_PASSWORD, SMTP_FROM (cai para SMTP_USER), SMTP_USE_TLS (default true),
  NOTIFICATION_EMAIL. Se SMTP_HOST e NOTIFICATION_EMAIL não estiverem setados, o envio
  deve ser um no-op (apenas log).
- O envio deve ser best-effort: qualquer falha é logada, nunca propaga exceção que
  quebre a operação principal. Use .strip() na senha (senhas de app do Google têm espaços).
- Dispare o e-mail quando <DESCREVA O EVENTO: ex. "um novo lead for criado no endpoint
  POST /leads">. Os dados do e-mail são: <LISTE OS CAMPOS: ex. nome, contato, id>.
- Atualize .env e .env.example com as novas variáveis.

No fim, faça um teste de envio e me mostre o resultado.
```

### 🔵 Prompt detalhado (Claude Code / Codex — passo a passo)

```
Implemente uma feature de notificação por e-mail via SMTP neste projeto Python/FastAPI.
Siga exatamente estes passos e me reporte ao final:

1. CONFIG: em <app/config.py> (Pydantic Settings), adicione os campos:
   smtp_host, smtp_port(=587), smtp_user, smtp_password, smtp_from, smtp_use_tls(=True),
   notification_email — com alias em MAIÚSCULAS. Adicione properties:
   - smtp_from_value -> smtp_from or smtp_user or ""
   - smtp_configured -> bool(smtp_host and notification_email)

2. SERVIÇO: crie <app/services/email_service.py> com:
   - _text_body(data) -> str (fallback texto)
   - _html_body(data) -> str (HTML inline, layout em tabela, header colorido com badge,
     função interna row(rotulo, valor), html.escape em todos os valores)
   - _build_message(data) -> EmailMessage (set_content + add_alternative subtype="html")
   - _send_sync(msg) -> usa smtplib.SMTP(host, port, timeout=15); se use_tls: starttls();
     se user e password: login(user, password.strip()); send_message
   - async send_notification(data): se not smtp_configured -> log e return; senão monta a
     mensagem e roda asyncio.to_thread(_send_sync, msg) dentro de try/except que só loga.

3. GATILHO: em <ROTA/ARQUIVO>, após <A OPERAÇÃO DE NEGÓCIO>, chame
   `await send_notification({...})` com os campos <CAMPOS>. Se precisar evitar duplicata,
   só envie quando <CONDIÇÃO/MUDANÇA DE VALOR>.

4. ENV: atualize .env e .env.example com as variáveis SMTP_* e NOTIFICATION_EMAIL.

5. TESTE: rode um envio real (ou mockado) e confirme o sucesso nos logs.

Importante: não adicione dependências externas; o envio não pode bloquear o event loop;
falha de e-mail nunca pode quebrar a operação principal.
```

### 🟢 Prompt para Cursor / agentes de edição inline

```
@codebase Quero adicionar envio de e-mail por SMTP (stdlib smtplib, multipart texto+HTML
com estilos inline). Crie app/services/email_service.py com uma função async
send_notification(data: dict) que: lê config SMTP de variáveis de ambiente
(SMTP_HOST/PORT/USER/PASSWORD/FROM/USE_TLS, NOTIFICATION_EMAIL); é no-op se não
configurado; envia via asyncio.to_thread; é best-effort (só loga erros). Adicione os
campos de config e chame a função em <local do evento>. Atualize .env.example.
Use html.escape nos valores e .strip() na senha.
```

### 🟡 Prompt para gerar/ajustar só o template HTML

```
Gere um template de e-mail HTML em Python (função que retorna string via f-string) para
notificação transacional. Requisitos: estilos 100% INLINE, layout baseado em <table>
(compatível com Gmail e Outlook), largura máx 520px, cantos arredondados, header com cor
de destaque <#HEX> contendo um badge, um título com emoji e subtítulo; corpo com uma
tabela de pares rótulo/valor gerada por uma função row(rotulo, valor); rodapé cinza
discreto. Todos os valores dinâmicos devem passar por html.escape. Campos a exibir:
<LISTE OS CAMPOS>.
```

---

> **Origem:** este guia foi gerado a partir de uma implementação real de notificação por
> e-mail no início de conversas (FastAPI + asyncpg + ElevenLabs). Adapte os nomes de
> campos, o ponto de gatilho e o visual ao seu domínio.
