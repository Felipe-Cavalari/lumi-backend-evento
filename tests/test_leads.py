"""Testes de integração do CRUD de leads (app/routes/leads.py)."""
import uuid

import pytest


async def _create_lead(client, headers, **overrides):
    """Helper: cria um lead via POST /api/leads e retorna o JSON."""
    payload = {
        "nome": "Maria Souza",
        "contato": "5511988887777",
        "empresa": "Beta S.A.",
        "contato_feito": False,
        "elevenlabs_conversation_id": None,
    }
    payload.update(overrides)
    resp = await client.post("/api/leads", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# POST /api/leads/register (público, com dedup)
# --------------------------------------------------------------------------- #


async def test_register_publico_sem_admin_key(client):
    resp = await client.post(
        "/api/leads/register",
        json={"nome": "João", "contato": "+5511900000000"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "lead_id" in body


async def test_register_remove_mais_do_contato(client, admin_headers):
    await client.post(
        "/api/leads/register", json={"nome": "João", "contato": "+5511900000000"}
    )
    # o '+' inicial deve ter sido removido antes de gravar
    resp = await client.get(
        "/api/leads/by-contato", params={"contato": "5511900000000"}, headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.json()["contato"] == "5511900000000"


async def test_register_dedup_por_contato(client):
    first = await client.post(
        "/api/leads/register", json={"nome": "João", "contato": "5511911112222"}
    )
    second = await client.post(
        "/api/leads/register", json={"nome": "Outro Nome", "contato": "5511911112222"}
    )
    assert first.json()["lead_id"] == second.json()["lead_id"]
    assert "já registrado" in second.json()["message"].lower()


# --------------------------------------------------------------------------- #
# POST /api/leads (admin)
# --------------------------------------------------------------------------- #


async def test_create_lead_ok(client, admin_headers):
    lead = await _create_lead(client, admin_headers)
    assert lead["nome"] == "Maria Souza"
    assert lead["contato"] == "5511988887777"
    assert lead["empresa"] == "Beta S.A."
    assert lead["contato_feito"] is False
    assert uuid.UUID(lead["id"])  # id é um UUID válido
    assert lead["timestamp"]  # created_at serializado


async def test_create_sem_admin_key_401(client):
    resp = await client.post(
        "/api/leads", json={"nome": "X", "contato": "5511000000001"}
    )
    assert resp.status_code == 401


async def test_create_contato_duplicado_409(client, admin_headers):
    await _create_lead(client, admin_headers, contato="5511955554444")
    resp = await client.post(
        "/api/leads",
        json={"nome": "Outro", "contato": "5511955554444"},
        headers=admin_headers,
    )
    assert resp.status_code == 409


# --------------------------------------------------------------------------- #
# GET /api/leads/list  e  /by-contato
# --------------------------------------------------------------------------- #


async def test_list_sem_admin_key_401(client):
    resp = await client.get("/api/leads/list")
    assert resp.status_code == 401


async def test_list_retorna_leads(client, admin_headers):
    await _create_lead(client, admin_headers, contato="5511000000010")
    await _create_lead(client, admin_headers, contato="5511000000011")
    resp = await client.get("/api/leads/list", headers=admin_headers)
    assert resp.status_code == 200
    assert len(resp.json()["leads"]) == 2


async def test_by_contato_404(client, admin_headers):
    resp = await client.get(
        "/api/leads/by-contato", params={"contato": "0000"}, headers=admin_headers
    )
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# GET /api/leads/{id}
# --------------------------------------------------------------------------- #


async def test_get_by_id_ok(client, admin_headers):
    lead = await _create_lead(client, admin_headers)
    resp = await client.get(f"/api/leads/{lead['id']}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == lead["id"]


async def test_get_by_id_invalido_400(client, admin_headers):
    resp = await client.get("/api/leads/nao-e-uuid", headers=admin_headers)
    assert resp.status_code == 400


async def test_get_by_id_inexistente_404(client, admin_headers):
    resp = await client.get(f"/api/leads/{uuid.uuid4()}", headers=admin_headers)
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# PUT /api/leads/{id}
# --------------------------------------------------------------------------- #


async def test_put_substitui_completo(client, admin_headers):
    lead = await _create_lead(client, admin_headers)
    resp = await client.put(
        f"/api/leads/{lead['id']}",
        json={
            "nome": "Maria Atualizada",
            "contato": "5511988887777",
            "empresa": "Beta Holding",
            "contato_feito": True,
            "elevenlabs_conversation_id": "conv_123",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["nome"] == "Maria Atualizada"
    assert body["contato_feito"] is True
    assert body["elevenlabs_conversation_id"] == "conv_123"


async def test_put_inexistente_404(client, admin_headers):
    resp = await client.put(
        f"/api/leads/{uuid.uuid4()}",
        json={"nome": "X", "contato": "5511000000099", "contato_feito": False},
        headers=admin_headers,
    )
    assert resp.status_code == 404


async def test_put_contato_duplicado_409(client, admin_headers):
    a = await _create_lead(client, admin_headers, contato="5511000000020")
    await _create_lead(client, admin_headers, contato="5511000000021")
    # tenta mudar o contato de 'a' para o de 'b'
    resp = await client.put(
        f"/api/leads/{a['id']}",
        json={"nome": "A", "contato": "5511000000021", "contato_feito": False},
        headers=admin_headers,
    )
    assert resp.status_code == 409


# --------------------------------------------------------------------------- #
# PATCH /api/leads/{id}
# --------------------------------------------------------------------------- #


async def test_patch_parcial(client, admin_headers):
    lead = await _create_lead(client, admin_headers)
    resp = await client.patch(
        f"/api/leads/{lead['id']}",
        json={"contato_feito": True},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["contato_feito"] is True
    assert body["nome"] == "Maria Souza"  # campos não enviados permanecem


async def test_patch_body_vazio_400(client, admin_headers):
    lead = await _create_lead(client, admin_headers)
    resp = await client.patch(
        f"/api/leads/{lead['id']}", json={}, headers=admin_headers
    )
    assert resp.status_code == 400


async def test_patch_inexistente_404(client, admin_headers):
    resp = await client.patch(
        f"/api/leads/{uuid.uuid4()}",
        json={"contato_feito": True},
        headers=admin_headers,
    )
    assert resp.status_code == 404


async def test_patch_empresa_endpoint(client, admin_headers):
    lead = await _create_lead(client, admin_headers)
    resp = await client.patch(
        f"/api/leads/{lead['id']}/empresa",
        json={"empresa": "Nova Empresa"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["empresa"] == "Nova Empresa"


async def test_patch_contato_feito_endpoint(client, admin_headers):
    lead = await _create_lead(client, admin_headers)
    resp = await client.patch(
        f"/api/leads/{lead['id']}/contato-feito",
        json={"contato_feito": True},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["contato_feito"] is True


# --------------------------------------------------------------------------- #
# DELETE /api/leads/{id}
# --------------------------------------------------------------------------- #


async def test_delete_ok(client, admin_headers):
    lead = await _create_lead(client, admin_headers)
    resp = await client.delete(f"/api/leads/{lead['id']}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["deleted_id"] == lead["id"]
    # confirma que sumiu
    get = await client.get(f"/api/leads/{lead['id']}", headers=admin_headers)
    assert get.status_code == 404


async def test_delete_inexistente_404(client, admin_headers):
    resp = await client.delete(f"/api/leads/{uuid.uuid4()}", headers=admin_headers)
    assert resp.status_code == 404
