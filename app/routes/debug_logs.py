"""Rotas para capturar logs do console do navegador."""
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/debug", tags=["debug"])

DEBUG_DIR = Path("data") / "debug" / "browser_logs"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)


class BrowserLogEntry(BaseModel):
    timestamp: Optional[str] = None
    level: str
    message: str


class BrowserLogBatch(BaseModel):
    session_id: str
    lead_email: Optional[str] = None
    entries: List[BrowserLogEntry] = Field(default_factory=list)


def sanitize_filename(value: str) -> str:
    """Sanitiza string para uso em nome de arquivo."""
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", value.strip())
    return safe[:120] or "unknown_session"


@router.post("/browser-logs")
async def save_browser_logs(batch: BrowserLogBatch):
    """Salva lotes de logs de console do navegador em arquivo."""
    if not batch.entries:
        return {"success": True, "written": 0}

    try:
        session_id = sanitize_filename(batch.session_id)
        log_file = DEBUG_DIR / f"{session_id}.log"
        first_write = not log_file.exists()

        with open(log_file, "a", encoding="utf-8") as f:
            if first_write:
                created_at = datetime.utcnow().isoformat()
                f.write(f"# Browser log session: {session_id}\n")
                f.write(f"# Created at (UTC): {created_at}\n")
                if batch.lead_email:
                    f.write(f"# Lead email: {batch.lead_email}\n")
                f.write("\n")

            for entry in batch.entries:
                ts = entry.timestamp or datetime.utcnow().isoformat()
                level = (entry.level or "log").upper()
                message = entry.message.replace("\n", "\\n")
                f.write(f"[{ts}] [{level}] {message}\n")

        return {
            "success": True,
            "written": len(batch.entries),
            "filepath": str(log_file),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar logs: {str(e)}")
