"""ElevenLabs usage service — minutos de conversa do agente (Conversational AI).

O custo do agente Lumi é cobrado por minuto de conversa, não por caractere de
TTS. Por isso a fonte é a lista de conversas (`/v1/convai/conversations`),
somando `call_duration_secs` por dia. O custo em USD é uma ESTIMATIVA
(minutos × `ELEVENLABS_COST_PER_MINUTE_USD`), já que o preço depende do plano
e o LLM é cobrado à parte.
"""
import asyncio
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

import httpx

from app.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

_ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"
_CACHE_TTL = 300  # 5 minutos
_PAGE_SIZE = 100  # máximo aceito pela API
_MAX_PAGES = 200  # trava de segurança contra paginação infinita


def _minutes(seconds: int) -> float:
    return round(seconds / 60, 2)


def _day_bounds_unix(start_date: date, end_date: date) -> tuple[int, int]:
    """Converte o período (datas UTC, inclusive) em timestamps unix."""
    start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return int(start.timestamp()), int(end.timestamp()) - 1


# ---------------------------------------------------------------------------
# Agregação
# ---------------------------------------------------------------------------

def _aggregate_conversations(
    conversations: list[dict],
    start_date: date,
    end_date: date,
    cost_per_minute: float,
) -> dict:
    """Agrega conversas por dia (UTC).

    Returns:
        {"total_conversations", "total_minutes", "cost",
         "daily_usage": [{"date", "conversations", "minutes", "cost"}]}
    """
    seconds_by_day: dict[str, int] = defaultdict(int)
    count_by_day: dict[str, int] = defaultdict(int)

    for conv in conversations:
        ts = conv.get("start_time_unix_secs") or 0
        if not ts:
            continue
        day = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        if not (start_date <= day <= end_date):
            continue
        key = day.isoformat()
        seconds_by_day[key] += int(conv.get("call_duration_secs") or 0)
        count_by_day[key] += 1

    daily_usage = []
    for day in sorted(count_by_day):
        minutes = _minutes(seconds_by_day[day])
        daily_usage.append({
            "date": day,
            "conversations": count_by_day[day],
            "minutes": minutes,
            "cost": round(minutes * cost_per_minute, 4),
        })

    total_minutes = _minutes(sum(seconds_by_day.values()))
    return {
        "total_conversations": sum(count_by_day.values()),
        "total_minutes": total_minutes,
        "cost": round(total_minutes * cost_per_minute, 4),
        "daily_usage": daily_usage,
    }


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

async def _fetch_subscription(api_key: str) -> Optional[int]:
    """Retorna os créditos restantes no plano (character_limit - character_count)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_ELEVENLABS_BASE}/user/subscription",
            headers={"xi-api-key": api_key},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    limit = data.get("character_limit", 0)
    used = data.get("character_count", 0)
    return max(0, limit - used)


async def _fetch_conversations(
    api_key: str,
    agent_id: Optional[str],
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Lista as conversas do agente no período, seguindo a paginação por cursor."""
    start_unix, end_unix = _day_bounds_unix(start_date, end_date)
    params: dict = {
        "page_size": _PAGE_SIZE,
        "call_start_after_unix": start_unix,
        "call_start_before_unix": end_unix,
    }
    if agent_id:
        params["agent_id"] = agent_id

    conversations: list[dict] = []
    async with httpx.AsyncClient() as client:
        for _ in range(_MAX_PAGES):
            resp = await client.get(
                f"{_ELEVENLABS_BASE}/convai/conversations",
                headers={"xi-api-key": api_key},
                params=params,
                timeout=15.0,
            )
            resp.raise_for_status()
            body = resp.json()
            conversations.extend(body.get("conversations", []))

            cursor = body.get("next_cursor")
            if not body.get("has_more") or not cursor:
                break
            params["cursor"] = cursor
        else:
            logger.warning("ElevenLabs: paginação interrompida após %d páginas", _MAX_PAGES)

    return conversations


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def get_elevenlabs_usage(
    api_key: str,
    agent_id: Optional[str],
    start_date: date,
    end_date: date,
    cost_per_minute: float,
) -> dict:
    """Retorna payload completo de uso ElevenLabs para o dashboard.

    Falha na lista de conversas propaga a exceção (a rota devolve erro); não
    há mais fallback com dados simulados, que podiam ser confundidos com reais.
    """
    cache_key = f"elevenlabs:usage:{agent_id}:{start_date}:{end_date}:{cost_per_minute}"
    cached = cache_get(cache_key, ttl=_CACHE_TTL)
    if cached is not None:
        logger.info("elevenlabs usage: cache hit")
        return cached

    conversations, subscription_result = await asyncio.gather(
        _fetch_conversations(api_key, agent_id, start_date, end_date),
        _fetch_subscription(api_key),
        return_exceptions=True,
    )

    if isinstance(conversations, BaseException):
        raise conversations

    if isinstance(subscription_result, BaseException):
        logger.warning("ElevenLabs subscription fetch falhou: %s", subscription_result)
        credits_left: Optional[int] = None
    else:
        credits_left = subscription_result

    payload: dict = {
        "provider": "elevenlabs",
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "cost_per_minute": cost_per_minute,
        "credits_left": credits_left,
        **_aggregate_conversations(conversations, start_date, end_date, cost_per_minute),
    }

    cache_set(cache_key, payload, ttl=_CACHE_TTL)
    return payload
