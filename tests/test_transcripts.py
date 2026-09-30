"""Testes das rotas de gravação (app/routes/transcripts.py e debug_logs.py)."""
import base64

import pytest

from app.routes import debug_logs, transcripts


@pytest.fixture(autouse=True)
def _tmp_data_dirs(tmp_path, monkeypatch):
    """Grava em diretórios temporários, nunca no data/ real."""
    monkeypatch.setattr(transcripts, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(transcripts, "AUDIO_DIR", tmp_path / "audio")
    monkeypatch.setattr(debug_logs, "DEBUG_DIR", tmp_path / "debug")
    (tmp_path / "transcripts").mkdir()
    (tmp_path / "audio").mkdir()
    (tmp_path / "debug").mkdir()
    return tmp_path


def _audio_payload(**overrides):
    payload = {
        "lead_email": "5511999990000",
        "lead_id": "abc",
        "speaker": "user",
        "audio_base64": base64.b64encode(b"fake-audio").decode(),
        "event_id": 1,
        "timestamp": "2026-09-30T10:00:00.000Z",
        "audio_format": "webm",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "path, body",
    [
        ("/api/transcripts/stt", {"lead_email": "x", "speaker": "user", "text": "oi"}),
        ("/api/transcripts/tts", _audio_payload()),
        ("/api/debug/browser-logs", {"session_id": "s", "entries": []}),
    ],
)
async def test_rotas_de_gravacao_exigem_admin_key(api_client, path, body):
    resp = await api_client.post(path, json=body)
    assert resp.status_code == 401


async def test_stt_salva_sem_expor_caminho(api_client, admin_headers, _tmp_data_dirs):
    resp = await api_client.post(
        "/api/transcripts/stt",
        json={"lead_email": "maria@gbpa.com.br", "speaker": "agent", "text": "Olá"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert "filepath" not in resp.json()
    files = list((_tmp_data_dirs / "transcripts").rglob("*.txt"))
    assert len(files) == 1
    assert "Text: Olá" in files[0].read_text(encoding="utf-8")


async def test_speaker_invalido_422(api_client, admin_headers):
    resp = await api_client.post(
        "/api/transcripts/stt",
        json={"lead_email": "x", "speaker": "../etc", "text": "oi"},
        headers=admin_headers,
    )
    assert resp.status_code == 422


@pytest.mark.parametrize("audio_format", ["webm", "mp4", "m4a", "ogg"])
async def test_formatos_do_browser_sao_salvos_sem_conversao(
    api_client, admin_headers, _tmp_data_dirs, audio_format
):
    """mp4 (Safari/iOS) não pode cair na conversão PCM → MP3, que gerava ruído."""
    resp = await api_client.post(
        "/api/transcripts/tts",
        json=_audio_payload(audio_format=audio_format),
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["format"] == audio_format
    files = list((_tmp_data_dirs / "audio").rglob(f"*.{audio_format}"))
    assert len(files) == 1
    assert files[0].read_bytes() == b"fake-audio"
    assert files[0].parent.name == "user_audio"


async def test_pcm_do_agente_e_convertido(api_client, admin_headers, _tmp_data_dirs):
    one_second_of_silence = b"\x00\x00" * 16000
    resp = await api_client.post(
        "/api/transcripts/tts",
        json=_audio_payload(
            speaker="agent",
            audio_format="pcm",
            audio_base64=base64.b64encode(one_second_of_silence).decode(),
        ),
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    # mp3 com ffmpeg instalado; wav/pcm são os fallbacks sem ele.
    assert body["format"] in {"mp3", "wav", "pcm"}
    assert "filepath" not in body
    files = list((_tmp_data_dirs / "audio" / "5511999990000" / "agent_audio").iterdir())
    assert len(files) == 1


async def test_base64_invalido_400(api_client, admin_headers):
    resp = await api_client.post(
        "/api/transcripts/tts",
        json=_audio_payload(audio_base64="não é base64!!"),
        headers=admin_headers,
    )
    assert resp.status_code == 400


async def test_browser_logs_sem_expor_caminho(api_client, admin_headers):
    resp = await api_client.post(
        "/api/debug/browser-logs",
        json={
            "session_id": "sessao-1",
            "entries": [{"level": "log", "message": "oi"}],
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "written": 1}
