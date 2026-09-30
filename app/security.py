"""Dependências de segurança reutilizáveis."""
import hmac
from typing import Optional

from fastapi import Header, HTTPException
from starlette.requests import Request

from app.config import settings


def is_valid_admin_key(candidate: Optional[str]) -> bool:
    """Compara a chave recebida com ``ADMIN_API_KEY`` em tempo constante (M-02)."""
    expected = settings.admin_api_key
    if not expected or not candidate:
        return False
    return hmac.compare_digest(candidate.encode(), expected.encode())


def is_trusted_proxy(request: Request) -> bool:
    """True quando a requisição veio do servidor Next (que envia ``X-Admin-Key``).

    Só nesse caso os headers de identidade repassados pelo proxy (ex.:
    ``X-Client-IP``) são confiáveis.
    """
    return is_valid_admin_key(request.headers.get("X-Admin-Key"))


async def require_admin_key(
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
) -> None:
    """
    Valida a chave de administração enviada no header ``X-Admin-Key``.

    Levanta 503 se ``ADMIN_API_KEY`` não estiver configurado no servidor e
    401 se a chave estiver ausente ou incorreta.
    """
    if not settings.admin_api_key:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_API_KEY não configurado no servidor. Contate o administrador.",
        )
    if not is_valid_admin_key(x_admin_key):
        raise HTTPException(
            status_code=401,
            detail="Chave de administração inválida ou ausente. "
                   "Envie o header 'X-Admin-Key: <chave>'.",
        )
