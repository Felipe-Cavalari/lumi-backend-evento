"""Rate limiting compartilhado (slowapi).

Instância única de ``Limiter`` importada tanto pelo ``main`` (para registrar o
handler de erro) quanto pelas rotas que aplicam ``@limiter.limit(...)``.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _client_ip(request: Request) -> str:
    """Identifica o cliente considerando proxy reverso (Coolify/Docker).

    Usa o primeiro IP de ``X-Forwarded-For`` quando presente; cai para o IP da
    conexão direta caso contrário. Atrás de um proxy confiável que reescreve
    esse header, é o identificador correto por cliente.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


# Sem default_limits global: os limites são aplicados por rota (decorator),
# evitando estrangular o stream de transcrição/áudio durante chamadas ativas.
limiter = Limiter(key_func=_client_ip)
