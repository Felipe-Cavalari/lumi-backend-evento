"""Testes das rotas que geram credencial da ElevenLabs (app/routes/elevenlabs.py)."""
import pytest

from app.config import settings

ROUTES = [
    ("GET", "/api/conversation/token"),
    ("GET", "/api/conversation/signed-url"),
    ("POST", "/api/token/realtime-scribe"),
]


@pytest.mark.parametrize("method, path", ROUTES)
async def test_credencial_exige_admin_key(api_client, method, path):
    """Sem a chave, quem tivesse a URL do backend pulava o cadastro do site."""
    resp = await api_client.request(method, path)
    assert resp.status_code == 401


@pytest.mark.parametrize("method, path", ROUTES)
async def test_admin_key_errada_e_recusada(api_client, method, path):
    resp = await api_client.request(method, path, headers={"X-Admin-Key": "errada"})
    assert resp.status_code == 401


@pytest.mark.parametrize("method, path", ROUTES)
async def test_admin_key_valida_passa_da_autorizacao(api_client, admin_headers, monkeypatch, method, path):
    # Sem a chave da ElevenLabs a rota para em 503 antes de sair para a rede:
    # chegar nele prova que a autorização deixou passar.
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    resp = await api_client.request(method, path, headers=admin_headers)
    assert resp.status_code == 503
