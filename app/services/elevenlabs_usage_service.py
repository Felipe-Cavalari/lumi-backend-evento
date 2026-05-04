"""ElevenLabs usage service — histórico de gerações, totalmente independente."""
import asyncio
import logging
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from app.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

_ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"
_CACHE_TTL = 300  # 5 minutos
_COST_PER_1K_CHARS = 0.30  # USD — ajustar conforme plano contratado


# ---------------------------------------------------------------------------
# Cálculo de custo
# ---------------------------------------------------------------------------

def _chars_to_cost(char_count: int) -> float:
    return round((char_count / 1000) * _COST_PER_1K_CHARS, 4)


# ---------------------------------------------------------------------------
# Agregação
# ---------------------------------------------------------------------------

def _aggregate_history(
    items: list[dict],
    start_date: date,
    end_date: date,
) -> tuple[int, list[dict]]:
    """Agrega itens de histórico por dia.

    Returns:
        total_usage: total de caracteres no período
        daily_usage: [{"date": str, "usage": int, "cost": float}]
    """
    daily: dict[str, int] = defaultdict(int)

    for item in items:
        ts = item.get("date_unix", 0)
        if not ts:
            continue
        item_date = datetime.utcfromtimestamp(ts).date()
        if not (start_date <= item_date <= end_date):
            continue
        chars = abs(int(item.get("character_count_change_from", 0) or 0))
        daily[item_date.isoformat()] += chars

    total = sum(daily.values())
    daily_usage = [
        {"date": day, "usage": count, "cost": _chars_to_cost(count)}
        for day, count in sorted(daily.items())
    ]
    return total, daily_usage


# ---------------------------------------------------------------------------
# Fetch real
# ---------------------------------------------------------------------------

async def _fetch_subscription(api_key: str) -> Optional[int]:
    """Retorna caracteres restantes no plano (character_limit - character_count).

    Retorna None se a chamada falhar, para não bloquear o resto do payload.
    """
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


async def _fetch_history(
    api_key: str,
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Busca histórico de gerações da API ElevenLabs.

    Itens são retornados do mais recente ao mais antigo; interrompe ao
    ultrapassar start_date para não baixar dados desnecessários.
    """
    start_ts = datetime.combine(start_date, datetime.min.time()).timestamp()
    items: list[dict] = []
    params: dict = {"page_size": 100}
    last_id: str | None = None

    async with httpx.AsyncClient() as client:
        while True:
            if last_id:
                params["start_after_history_item_id"] = last_id

            resp = await client.get(
                f"{_ELEVENLABS_BASE}/history",
                headers={"xi-api-key": api_key},
                params=params,
                timeout=15.0,
            )
            resp.raise_for_status()
            body = resp.json()
            page = body.get("history", [])

            if not page:
                break

            stop = False
            for item in page:
                item_ts = item.get("date_unix", 0)
                if item_ts < start_ts:
                    stop = True
                    break
                items.append(item)

            if stop or not body.get("has_more"):
                break

            last_id = page[-1].get("history_item_id")
            if not last_id:
                break

    return items


# ---------------------------------------------------------------------------
# Mock estruturado (fallback quando API indisponível)
# ---------------------------------------------------------------------------

def _generate_mock(start_date: date, end_date: date) -> tuple[int, list[dict]]:
    """Gera dados sintéticos para desenvolvimento/fallback."""
    rng = random.Random(str(start_date))
    days = (end_date - start_date).days + 1
    daily: list[dict] = []
    total = 0

    for i in range(days):
        day = start_date + timedelta(days=i)
        usage = rng.randint(3000, 12000)
        total += usage
        daily.append({
            "date": day.isoformat(),
            "usage": usage,
            "cost": _chars_to_cost(usage),
        })

    return total, daily


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def get_elevenlabs_usage(
    api_key: str,
    start_date: date,
    end_date: date,
) -> dict:
    """Retorna payload completo de uso ElevenLabs para o dashboard."""
    cache_key = f"elevenlabs:usage:{start_date}:{end_date}"
    cached = cache_get(cache_key, ttl=_CACHE_TTL)
    if cached is not None:
        logger.info("elevenlabs usage: cache hit")
        return cached

    is_mock = False

    # Executa history e subscription em paralelo, com falhas independentes
    history_result, subscription_result = await asyncio.gather(
        _fetch_history(api_key, start_date, end_date),
        _fetch_subscription(api_key),
        return_exceptions=True,
    )

    if isinstance(subscription_result, Exception):
        logger.warning("ElevenLabs subscription fetch falhou: %s", subscription_result)
        total_left: Optional[int] = None
    else:
        total_left = subscription_result

    if isinstance(history_result, Exception):
        exc = history_result
        if isinstance(exc, httpx.HTTPStatusError):
            logger.warning("ElevenLabs API retornou %s — usando mock", exc.response.status_code)
        else:
            logger.warning("ElevenLabs history fetch falhou: %s — usando mock", exc)
        total_usage, daily_usage = _generate_mock(start_date, end_date)
        is_mock = True
    else:
        total_usage, daily_usage = _aggregate_history(history_result, start_date, end_date)

    payload: dict = {
        "provider": "elevenlabs",
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "total_usage": total_usage,
        "total_left": total_left,
        "cost": _chars_to_cost(total_usage),
        "daily_usage": daily_usage,
    }
    if is_mock:
        payload["_mock"] = True

    cache_set(cache_key, payload, ttl=_CACHE_TTL)
    return payload
