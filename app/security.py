"""Dependências de segurança reutilizáveis."""
from typing import Optional

from fastapi import Header, HTTPException

from app.config import settings


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
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(
            status_code=401,
            detail="Chave de administração inválida ou ausente. "
                   "Envie o header 'X-Admin-Key: <chave>'.",
        )
