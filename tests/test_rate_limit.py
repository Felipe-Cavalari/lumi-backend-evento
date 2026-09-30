"""Testes da identificação do cliente no rate limit (app/rate_limit.py)."""
import pytest
from starlette.requests import Request

from app.config import settings
from app.rate_limit import _client_ip

ADMIN_KEY = "test-admin-key"


@pytest.fixture(autouse=True)
def _admin_key(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", ADMIN_KEY)


def _request(headers: dict, client_host: str = "10.0.0.5") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (client_host, 12345),
    }
    return Request(scope)


def test_x_client_ip_aceito_do_proxy_confiavel():
    req = _request({"X-Admin-Key": ADMIN_KEY, "X-Client-IP": "200.1.2.3"})
    assert _client_ip(req) == "200.1.2.3"


def test_x_client_ip_ignorado_sem_admin_key():
    """Sem a chave, o header é forjável e não pode definir o balde."""
    req = _request({"X-Client-IP": "200.1.2.3"})
    assert _client_ip(req) == "10.0.0.5"


def test_x_client_ip_ignorado_com_admin_key_errada():
    req = _request({"X-Admin-Key": "errada", "X-Client-IP": "200.1.2.3"})
    assert _client_ip(req) == "10.0.0.5"


def test_x_forwarded_for_usa_o_ultimo_hop():
    """O primeiro IP é controlado pelo cliente; o último foi visto pelo proxy."""
    req = _request({"X-Forwarded-For": "1.1.1.1, 172.16.0.9"})
    assert _client_ip(req) == "172.16.0.9"


def test_sem_headers_usa_ip_da_conexao():
    assert _client_ip(_request({})) == "10.0.0.5"
