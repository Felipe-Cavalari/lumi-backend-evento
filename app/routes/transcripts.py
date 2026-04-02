"""Rotas para salvar transcrições STT e áudios TTS."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import ClassVar, Optional
import os
import base64
import io
import shutil
import traceback
from datetime import datetime
from pathlib import Path
from pydub import AudioSegment

from app.security import require_admin_key

router = APIRouter(prefix="/api/transcripts", tags=["transcripts"])


class TranscriptData(BaseModel):
    lead_email: str
    speaker: str  # "user" ou "agent"
    text: str
    timestamp: Optional[str] = None


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


def get_lead_dir(lead_email: str) -> Path:
    """Retorna o diretório do lead, criando se necessário."""
    # Sanitizar email para nome de diretório
    safe_email = lead_email.replace("@", "_at_").replace(".", "_")
    # Remover caracteres inválidos
    safe_email = "".join(c for c in safe_email if c.isalnum() or c in ["_", "-"])
    lead_dir = TRANSCRIPTS_DIR / safe_email
    lead_dir.mkdir(parents=True, exist_ok=True)
    print(f"[STT] Diretório do lead: {lead_dir}")  # Debug log
    return lead_dir


def get_audio_dir(lead_email: str, speaker: str = "user") -> Path:
    """
    Retorna o diretório de áudio do lead, criando se necessário.
    Organiza em subpastas: user_audio/ e agent_audio/
    
    Args:
        lead_email: Email do lead
        speaker: "user" ou "agent" para determinar a subpasta
    """
    safe_email = lead_email.replace("@", "_at_").replace(".", "_")
    # Remover caracteres inválidos
    safe_email = "".join(c for c in safe_email if c.isalnum() or c in ["_", "-"])
    
    # Determinar subpasta baseado no speaker
    if speaker == "agent":
        subfolder = "agent_audio"
    else:
        subfolder = "user_audio"
    
    # Criar estrutura: data/audio/{email}/user_audio/ ou data/audio/{email}/agent_audio/
    audio_dir = AUDIO_DIR / safe_email / subfolder
    audio_dir.mkdir(parents=True, exist_ok=True)
    print(f"[TTS] Diretório de áudio do lead ({speaker}): {audio_dir}")  # Debug log
    return audio_dir


@router.post("/stt")
async def save_stt_transcript(transcript: TranscriptData):
    """
    Salva uma transcrição STT em arquivo de texto.
    
    Referência: https://docs.python.org/3/library/pathlib.html
    """
    try:
        print(f"[STT] Recebendo transcrição: email={transcript.lead_email}, speaker={transcript.speaker}, text={transcript.text[:50]}...")
        
        lead_dir = get_lead_dir(transcript.lead_email)
        timestamp = transcript.timestamp or datetime.now().isoformat()
        
        # Nome do arquivo: timestamp_speaker.txt
        # Sanitizar timestamp para nome de arquivo válido
        safe_timestamp = timestamp.replace(":", "-").replace(".", "-").replace("T", "_").replace("Z", "")
        # Remover caracteres inválidos restantes
        safe_timestamp = "".join(c for c in safe_timestamp if c.isalnum() or c in ["-", "_"])
        filename = f"{safe_timestamp}_{transcript.speaker}.txt"
        filepath = lead_dir / filename
        
        print(f"[STT] Salvando em: {filepath}")
        
        # Salvar transcrição
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"Timestamp: {timestamp}\n")
            f.write(f"Speaker: {transcript.speaker}\n")
            f.write(f"Text: {transcript.text}\n")
        
        print(f"[STT] Arquivo salvo com sucesso: {filepath}")
        
        return {
            "success": True,
            "message": "Transcrição salva com sucesso",
            "filepath": str(filepath),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao salvar transcrição: {str(e)}"
        )


@router.post("/tts")
async def save_tts_audio(audio: AudioData):
    """
    Salva um áudio TTS ou STT (usuário) em arquivo MP3.
    
    Referência: 
    - https://docs.python.org/3/library/base64.html
    - https://github.com/jiaaro/pydub
    """
    try:
        print(f"[TTS] Recebendo áudio: email={audio.lead_email}, speaker={audio.speaker}, lead_id={audio.lead_id}")
        
        # Usar speaker para determinar a subpasta (user_audio ou agent_audio)
        audio_dir = get_audio_dir(audio.lead_email, speaker=audio.speaker)
        timestamp = audio.timestamp or datetime.now().isoformat()
        
        # Decodificar base64
        try:
            audio_bytes = base64.b64decode(audio.audio_base64)
        except Exception as decode_error:
            print(f"[TTS] Erro ao decodificar base64: {decode_error}")
            raise HTTPException(
                status_code=400,
                detail=f"Erro ao decodificar áudio base64: {str(decode_error)}"
            )
        
        # Preparar nome do arquivo base
        safe_timestamp = timestamp.replace(":", "-").replace(".", "-").replace("T", "_").replace("Z", "")
        safe_timestamp = "".join(c for c in safe_timestamp if c.isalnum() or c in ["-", "_"])
        event_id = audio.event_id or 0
        
        # Para formatos já encapsulados (ex.: gravação do browser), salvar bytes crus
        passthrough_formats = {"webm", "ogg", "wav", "mp3", "m4a"}
        incoming_format = (audio.audio_format or "").lower().strip()
        if incoming_format in passthrough_formats:
            filename = f"{safe_timestamp}_{audio.speaker}_{event_id}.{incoming_format}"
            filepath = audio_dir / filename
            with open(filepath, "wb") as f:
                f.write(audio_bytes)
            print(f"[TTS] Áudio {incoming_format.upper()} salvo (passthrough): {filepath}")
            return {
                "success": True,
                "message": f"Áudio salvo com sucesso em formato {incoming_format.upper()}",
                "filepath": str(filepath),
                "format": incoming_format,
                "lead_id": audio.lead_id,
            }

        # Converter PCM para MP3 (padrão para áudio do agente)
        audio_format = "mp3"
        audio_segment = None
        try:
            # Criar AudioSegment a partir de bytes PCM (16-bit, mono)
            # O áudio vem em formato PCM 16-bit do Conversational AI (16kHz) ou do usuário (16kHz)
            # Ambos usam 16kHz conforme metadata: agent_output_audio_format: "pcm_16000"
            sample_rate = 16000
            audio_segment = AudioSegment(
                audio_bytes,
                frame_rate=sample_rate,
                channels=1,
                sample_width=2  # 16-bit = 2 bytes
            )
            
            # Converter para MP3 usando ffmpeg (requer ffmpeg instalado)
            # Referência: https://github.com/jiaaro/pydub#getting-ffmpeg-set-up
            mp3_buffer = io.BytesIO()
            audio_segment.export(mp3_buffer, format="mp3", bitrate="128k")
            mp3_bytes = mp3_buffer.getvalue()
            
            print(f"[TTS] Áudio convertido: PCM {len(audio_bytes)} bytes -> MP3 {len(mp3_bytes)} bytes")
        except Exception as convert_error:
            print(f"[TTS] Erro ao converter para MP3: {convert_error}")
            print(f"[TTS] Verifique se ffmpeg está instalado: brew install ffmpeg (macOS) ou apt-get install ffmpeg (Linux)")
            # Se a conversão falhar, tentar salvar como WAV (formato mais compatível)
            try:
                if audio_segment is not None:
                    wav_buffer = io.BytesIO()
                    audio_segment.export(wav_buffer, format="wav")
                    mp3_bytes = wav_buffer.getvalue()
                    audio_format = "wav"
                    print(f"[TTS] Salvando como WAV devido ao erro de conversão MP3")
                else:
                    mp3_bytes = audio_bytes
                    audio_format = "pcm"
                    print(f"[TTS] Salvando como PCM original (AudioSegment indisponível)")
            except Exception as wav_error:
                # Se tudo falhar, salvar como PCM original
                print(f"[TTS] Salvando como PCM original devido ao erro de conversão")
                mp3_bytes = audio_bytes
                audio_format = "pcm"
        
        # Nome do arquivo: timestamp_speaker_eventId.{format}
        filename = f"{safe_timestamp}_{audio.speaker}_{event_id}.{audio_format}"
        filepath = audio_dir / filename
        
        print(f"[TTS] Salvando áudio {audio_format.upper()} em: {filepath}, tamanho: {len(mp3_bytes)} bytes")
        
        # Salvar áudio
        with open(filepath, "wb") as f:
            f.write(mp3_bytes)
        
        print(f"[TTS] Áudio {audio_format.upper()} salvo com sucesso: {filepath}")
        
        return {
            "success": True,
            "message": f"Áudio salvo com sucesso em formato {audio_format.upper()}",
            "filepath": str(filepath),
            "format": audio_format,
            "lead_id": audio.lead_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[TTS] Erro ao salvar áudio: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao salvar áudio: {str(e)}"
        )


@router.delete("/audio/all", dependencies=[Depends(require_admin_key)])
async def delete_all_audios():
    """
    Deleta todos os arquivos de áudio em data/audio/ recursivamente.
    Requer header X-Admin-Key válido.
    """
    deleted_files = 0
    deleted_dirs = 0

    if not AUDIO_DIR.exists():
        return {
            "success": True,
            "message": "Diretório de áudio não encontrado, nada a deletar.",
            "deleted_files": 0,
            "deleted_dirs": 0,
        }

    for item in list(AUDIO_DIR.iterdir()):
        if item.is_dir():
            file_count = sum(1 for _ in item.rglob("*") if _.is_file())
            shutil.rmtree(item)
            deleted_files += file_count
            deleted_dirs += 1
        else:
            item.unlink()
            deleted_files += 1

    print(f"[AUDIO] Deletados {deleted_files} arquivo(s) em {deleted_dirs} diretório(s) de {AUDIO_DIR}")

    return {
        "success": True,
        "message": f"Todos os áudios foram deletados com sucesso.",
        "deleted_files": deleted_files,
        "deleted_dirs": deleted_dirs,
    }


@router.delete("/transcripts/all", dependencies=[Depends(require_admin_key)])
async def delete_all_transcripts():
    """
    Deleta todos os arquivos de transcrição em data/transcripts/ recursivamente.
    Requer header X-Admin-Key válido.
    """
    deleted_files = 0
    deleted_dirs = 0

    if not TRANSCRIPTS_DIR.exists():
        return {
            "success": True,
            "message": "Diretório de transcrições não encontrado, nada a deletar.",
            "deleted_files": 0,
            "deleted_dirs": 0,
        }

    for item in list(TRANSCRIPTS_DIR.iterdir()):
        if item.is_dir():
            file_count = sum(1 for _ in item.rglob("*") if _.is_file())
            shutil.rmtree(item)
            deleted_files += file_count
            deleted_dirs += 1
        else:
            item.unlink()
            deleted_files += 1

    print(f"[TRANSCRIPTS] Deletados {deleted_files} arquivo(s) em {deleted_dirs} diretório(s) de {TRANSCRIPTS_DIR}")

    return {
        "success": True,
        "message": "Todas as transcrições foram deletadas com sucesso.",
        "deleted_files": deleted_files,
        "deleted_dirs": deleted_dirs,
    }
