"""Envio de e-mail de notificação de início de conversa via SMTP."""
import asyncio
import logging
import smtplib
from email.message import EmailMessage
from html import escape

from app.config import settings

logger = logging.getLogger(__name__)

_ACCENT = "#2563eb"  # azul de destaque do template


def _text_body(lead: dict) -> str:
    return (
        "Um cliente iniciou uma nova conversa.\n\n"
        f"Nome: {lead.get('nome') or '(sem nome)'}\n"
        f"Contato: {lead.get('contato') or '(sem contato)'}\n"
        f"ID ElevenLabs: {lead.get('elevenlabs_conversation_id') or '(não informado)'}\n"
    )


def _html_body(lead: dict) -> str:
    nome = escape(lead.get("nome") or "(sem nome)")
    contato = escape(lead.get("contato") or "(sem contato)")
    conversation_id = escape(lead.get("elevenlabs_conversation_id") or "(não informado)")

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
              <div style="display:inline-block;background:rgba(255,255,255,0.18);color:#ffffff;font-size:12px;font-weight:600;letter-spacing:0.5px;text-transform:uppercase;padding:4px 10px;border-radius:999px;">Conversa iniciada</div>
              <h1 style="margin:12px 0 0;color:#ffffff;font-size:22px;font-weight:700;">Novo cliente em conversa 🎙️</h1>
              <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:14px;">Um cliente acabou de iniciar uma conversa com o agente.</p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 28px 8px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #f0f0f0;border-radius:8px;overflow:hidden;">
                {row("Nome", nome)}
                {row("Contato", contato)}
                {row("ID ElevenLabs", conversation_id)}
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 28px 28px;">
              <p style="margin:0;color:#9ca3af;font-size:12px;line-height:1.5;">
                Este e-mail foi enviado automaticamente pelo backend da Lumi.<br>
                Você está recebendo porque foi configurado como destinatário das notificações de leads.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _build_message(lead: dict) -> EmailMessage:
    nome = lead.get("nome") or "(sem nome)"

    msg = EmailMessage()
    msg["Subject"] = f"Conversa iniciada: {nome}"
    msg["From"] = settings.smtp_from_value
    msg["To"] = settings.lead_notification_email
    msg.set_content(_text_body(lead))  # fallback texto puro
    msg.add_alternative(_html_body(lead), subtype="html")
    return msg


def _send_sync(msg: EmailMessage) -> None:
    """Envio bloqueante — chamado via asyncio.to_thread para não travar o event loop."""
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_user and settings.smtp_password:
            # senhas de app do Google são exibidas com espaços; o strip evita falha de login.
            server.login(settings.smtp_user, settings.smtp_password.strip())
        server.send_message(msg)


async def send_lead_notification(lead: dict) -> None:
    """Envia (best-effort) o e-mail de notificação de início de conversa.

    Deve ser chamado apenas quando o cliente inicia uma conversa (lead com
    elevenlabs_conversation_id). Falhas são apenas logadas — nunca devem
    quebrar o registro do lead.
    """
    if not settings.smtp_configured:
        logger.info("SMTP não configurado; e-mail de notificação de lead ignorado.")
        return
    try:
        msg = _build_message(lead)
        await asyncio.to_thread(_send_sync, msg)
        logger.info(
            "E-mail de início de conversa enviado para %s",
            settings.lead_notification_email,
        )
    except Exception:
        logger.exception("Falha ao enviar e-mail de notificação de lead")
