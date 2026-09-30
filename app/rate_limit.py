"""Rate limiting compartilhado (slowapi).

Instância única de ``Limiter`` importada tanto pelo ``main`` (para registrar o
handler de erro) quanto pelas rotas que aplicam ``@limiter.limit(...)``.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.security import is_trusted_proxy


def _client_ip(request: Request) -> str:
    """Identifica o visitante para o rate limit.

    1. ``X-Client-IP`` — IP do visitante repassado pelo servidor Next. Só é
       aceito quando a requisição traz ``X-Admin-Key`` válida; sem isso,
       qualquer cliente poderia forjar o header e escapar do limite.
    2. Último IP de ``X-Forwarded-For`` — o que o proxy reverso
       (Coolify/Traefik) realmente viu. O primeiro IP é controlado pelo
       cliente e não serve como identificador.
    3. IP da conexão direta.

    Sem o passo 1, todo visitante que passa pelo Next apareceria com o mesmo
    IP (o do servidor Next) e dividiria um único balde.
    """
    if is_trusted_proxy(request):
        client_ip = (request.headers.get("X-Client-IP") or "").strip()
        if client_ip:
            return client_ip

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        last_hop = forwarded.split(",")[-1].strip()
        if last_hop:
            return last_hop
    return get_remote_address(request)


# Sem default_limits global: os limites são aplicados por rota (decorator),
# evitando estrangular o stream de transcrição/áudio durante chamadas ativas.
limiter = Limiter(key_func=_client_ip)
