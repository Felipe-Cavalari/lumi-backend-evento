"""Rotas para salvar transcrições STT e áudios TTS."""
import asyncio
import base64
import io
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from pydub import AudioSegment

from app.rate_limit import limiter
from app.security import require_admin_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/transcripts", tags=["transcripts"])

# Formatos já encapsulados (gravação do browser): salvos como vieram, sem ffmpeg.
# mp4/m4a/aac vêm do MediaRecorder do Safari/iOS.
PASSTHROUGH_FORMATS = {"webm", "ogg", "wav", "mp3", "m4a", "mp4", "aac"}

# Áudio do agente chega em PCM 16-bit mono 16 kHz
# (metadata ElevenLabs: agent_output_audio_format = "pcm_16000").
PCM_SAMPLE_RATE = 16000


def _validate_speaker(v: str) -> str:
    """Fix C-01: speaker entra no nome do arquivo, então só pode ser
    'user' ou 'agent' — elimina o vetor de path traversal."""
    normalized = (v or "").strip().lower()
    if normalized not in {"user", "agent"}:
        raise ValueError("speaker deve ser 'user' ou 'agent'")
    return normalized


class TranscriptData(BaseModel):
    lead_email: str
    lead_id: Optional[str] = None
    speaker: str  # "user" ou "agent"
    text: str
    timestamp: Optional[str] = None

    _validate_speaker = field_validator("speaker")(staticmethod(_validate_speaker))


class AudioData(BaseModel):
    lead_email: str
    lead_id: Optional[str] = None
    speaker: str  # "user" ou "agent"
    audio_base64: str
    event_id: Optional[int] = None
    timestamp: Optional[str] = None
    audio_format: Optional[str] = None

    # Fix V-03: limite de 20 MB no payload base64 (~15 MB de áudio bruto)
    # ClassVar é necessário para que o Pydantic v2 não trate como ModelPrivateAttr
    MAX_BASE64_BYTES: ClassVar[int] = 20 * 1024 * 1024  # 20 MB

    _validate_speaker = field_validator("speaker")(staticmethod(_validate_speaker))

    @field_validator("audio_base64")
    @classmethod
    def validate_audio_size(cls, v: str) -> str:
        if len(v) > cls.MAX_BASE64_BYTES:
            size_mb = len(v) / 1024 / 1024
            raise ValueError(
                f"Payload de áudio excede o limite de 20 MB "
                f"(recebido: {size_mb:.1f} MB). Envie segmentos menores."
            )  # noqa: E501
        return v


# Garantir que os diretórios existem
DATA_DIR = Path("data")
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
AUDIO_DIR = DATA_DIR / "audio"

DATA_DIR.mkdir(exist_ok=True)
TRANSCRIPTS_DIR.mkdir(exist_ok=True)
AUDIO_DIR.mkdir(exist_ok=True)


def _ensure_within(base: Path, target: Path) -> Path:
    """Fix C-01: garante que ``target`` está contido em ``base`` (anti path
    traversal). Defesa em profundidade — o nome final do arquivo nunca pode
    escapar do diretório de dados, independentemente do input."""
    base_r = base.resolve()
    target_r = target.resolve()
    if base_r != target_r and base_r not in target_r.parents:
        raise HTTPException(status_code=400, detail="Caminho de arquivo inválido.")
    return target_r


def _safe_lead_folder(lead_email: str) -> str:
    """Converte o contato (e-mail ou telefone) em nome de diretório seguro."""
    safe = lead_email.replace("@", "_at_").replace(".", "_")
    return "".join(c for c in safe if c.isalnum() or c in ["_", "-"])


def _safe_timestamp(timestamp: str) -> str:
    safe = timestamp.replace(":", "-").replace(".", "-").replace("T", "_").replace("Z", "")
    return "".join(c for c in safe if c.isalnum() or c in ["-", "_"])


def _mask_contact(contact: str) -> str:
    """Evita gravar o contato completo (dado pessoal) nos logs."""
    return f"***{contact[-4:]}" if len(contact) > 4 else "***"


def get_lead_dir(lead_email: str) -> Path:
    """Retorna o diretório do lead, criando se necessário."""
    lead_dir = TRANSCRIPTS_DIR / _safe_lead_folder(lead_email)
    lead_dir.mkdir(parents=True, exist_ok=True)
    return lead_dir


def get_audio_dir(lead_email: str, speaker: str = "user") -> Path:
    """
    Retorna o diretório de áudio do lead, criando se necessário.
    Organiza em subpastas: data/audio/{contato}/user_audio/ e agent_audio/
    """
    subfolder = "agent_audio" if speaker == "agent" else "user_audio"
    audio_dir = AUDIO_DIR / _safe_lead_folder(lead_email) / subfolder
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir


def _write_text(filepath: Path, content: str) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def _write_bytes(filepath: Path, content: bytes) -> None:
    with open(filepath, "wb") as f:
        f.write(content)


def _encode_pcm(pcm_bytes: bytes) -> tuple[bytes, str]:
    """Converte PCM cru em MP3 (fallback: WAV, depois o próprio PCM).

    Operação CPU-bound que chama o ffmpeg como subprocesso: deve rodar fora do
    event loop (``asyncio.to_thread``) para não travar as demais requisições.
    """
    try:
        segment = AudioSegment(
            pcm_bytes,
            frame_rate=PCM_SAMPLE_RATE,
            channels=1,
            sample_width=2,  # 16-bit
        )
    except Exception:
        logger.exception("[TTS] PCM inválido; salvando bytes crus")
        return pcm_bytes, "pcm"

    try:
        buffer = io.BytesIO()
        segment.export(buffer, format="mp3", bitrate="128k")
        return buffer.getvalue(), "mp3"
    except Exception:
        logger.exception("[TTS] Falha ao converter para MP3 (ffmpeg instalado?); tentando WAV")

    try:
        buffer = io.BytesIO()
        segment.export(buffer, format="wav")
        return buffer.getvalue(), "wav"
    except Exception:
        logger.exception("[TTS] Falha ao converter para WAV; salvando PCM cru")
        return pcm_bytes, "pcm"


# As rotas de gravação exigem X-Admin-Key: só o servidor Next pode chamá-las,
# depois de validar o token do lead do visitante. Sem isso, qualquer anônimo
# gravaria arquivos arbitrários em disco.


@router.post("/stt", dependencies=[Depends(require_admin_key)])
@limiter.limit("120/minute")
async def save_stt_transcript(request: Request, transcript: TranscriptData):
    """Salva uma transcrição (fala do usuário ou do agente) em arquivo de texto."""
    try:
        lead_dir = get_lead_dir(transcript.lead_email)
        timestamp = transcript.timestamp or datetime.now().isoformat()
        filename = f"{_safe_timestamp(timestamp)}_{transcript.speaker}.txt"
        filepath = _ensure_within(TRANSCRIPTS_DIR, lead_dir / filename)

        content = (
            f"Timestamp: {timestamp}\n"
            f"Speaker: {transcript.speaker}\n"
            f"Text: {transcript.text}\n"
        )
        await asyncio.to_thread(_write_text, filepath, content)

        logger.info(
            "[STT] Transcrição salva: contato=%s speaker=%s",
            _mask_contact(transcript.lead_email),
            transcript.speaker,
        )
        return {"success": True, "message": "Transcrição salva com sucesso"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("[STT] Erro ao salvar transcrição")
        raise HTTPException(status_code=500, detail="Erro ao salvar transcrição.")


@router.post("/tts", dependencies=[Depends(require_admin_key)])
@limiter.limit("120/minute")
async def save_tts_audio(request: Request, audio: AudioData):
    """Salva um segmento de áudio do agente (PCM → MP3) ou do usuário (passthrough)."""
    try:
        try:
            audio_bytes = base64.b64decode(audio.audio_base64, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="Áudio base64 inválido.")

        audio_dir = get_audio_dir(audio.lead_email, speaker=audio.speaker)
        timestamp = audio.timestamp or datetime.now().isoformat()
        event_id = audio.event_id or 0

        incoming_format = (audio.audio_format or "").lower().strip()
        if incoming_format in PASSTHROUGH_FORMATS:
            file_bytes, audio_format = audio_bytes, incoming_format
        else:
            file_bytes, audio_format = await asyncio.to_thread(_encode_pcm, audio_bytes)

        filename = f"{_safe_timestamp(timestamp)}_{audio.speaker}_{event_id}.{audio_format}"
        filepath = _ensure_within(AUDIO_DIR, audio_dir / filename)
        await asyncio.to_thread(_write_bytes, filepath, file_bytes)

        logger.info(
            "[TTS] Áudio salvo: contato=%s speaker=%s formato=%s bytes=%d",
            _mask_contact(audio.lead_email),
            audio.speaker,
            audio_format,
            len(file_bytes),
        )
        return {
            "success": True,
            "message": f"Áudio salvo com sucesso em formato {audio_format.upper()}",
            "format": audio_format,
            "lead_id": audio.lead_id,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("[TTS] Erro ao salvar áudio")
        raise HTTPException(status_code=500, detail="Erro ao salvar áudio.")


def _delete_children(base: Path) -> tuple[int, int]:
    """Remove todo o conteúdo de ``base``; retorna (arquivos, diretórios) removidos."""
    deleted_files = 0
    deleted_dirs = 0
    for item in list(base.iterdir()):
        if item.is_dir():
            deleted_files += sum(1 for f in item.rglob("*") if f.is_file())
            shutil.rmtree(item)
            deleted_dirs += 1
        else:
            item.unlink()
            deleted_files += 1
    return deleted_files, deleted_dirs


@router.delete("/audio/all", dependencies=[Depends(require_admin_key)])
async def delete_all_audios():
    """
    Deleta todos os arquivos de áudio em data/audio/ recursivamente.
    Requer header X-Admin-Key válido.
    """
    if not AUDIO_DIR.exists():
        return {
            "success": True,
            "message": "Diretório de áudio não encontrado, nada a deletar.",
            "deleted_files": 0,
            "deleted_dirs": 0,
        }

    deleted_files, deleted_dirs = await asyncio.to_thread(_delete_children, AUDIO_DIR)
    logger.info("[AUDIO] Deletados %d arquivo(s) em %d diretório(s)", deleted_files, deleted_dirs)

    return {
        "success": True,
        "message": "Todos os áudios foram deletados com sucesso.",
        "deleted_files": deleted_files,
        "deleted_dirs": deleted_dirs,
    }


@router.delete("/transcripts/all", dependencies=[Depends(require_admin_key)])
async def delete_all_transcripts():
    """
    Deleta todos os arquivos de transcrição em data/transcripts/ recursivamente.
    Requer header X-Admin-Key válido.
    """
    if not TRANSCRIPTS_DIR.exists():
        return {
            "success": True,
            "message": "Diretório de transcrições não encontrado, nada a deletar.",
            "deleted_files": 0,
            "deleted_dirs": 0,
        }

    deleted_files, deleted_dirs = await asyncio.to_thread(_delete_children, TRANSCRIPTS_DIR)
    logger.info("[TRANSCRIPTS] Deletados %d arquivo(s) em %d diretório(s)", deleted_files, deleted_dirs)

    return {
        "success": True,
        "message": "Todas as transcrições foram deletadas com sucesso.",
        "deleted_files": deleted_files,
        "deleted_dirs": deleted_dirs,
    }
