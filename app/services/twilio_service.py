"""Twilio usage service — balance + daily usage records, totalmente independente."""
import asyncio
import logging
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

import httpx

from app.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

_TWILIO_BASE = "https://api.twilio.com/2010-04-01"
_CACHE_TTL = 300  # 5 minutos

# Mapeamento de categorias Twilio → grupos do dashboard.
#
# As categorias da Twilio são hierárquicas: `calls` já inclui `calls-inbound`,
# que inclui `calls-inbound-local`, e assim por diante. Somar pai e filhos
# multiplica o custo. Por isso cada grupo lista só categorias SEM sobreposição:
# - voice: `calls` (não inclui SIP nem Client, que vêm à parte);
# - sms: `sms` (total de SMS de entrada e saída);
# - whatsapp: as taxas `channels-whatsapp-*` (folhas, sem o pai).
# Ref.: https://www.twilio.com/docs/usage/api/usage-record
_VOICE_CATEGORIES = {"calls", "calls-client", "calls-sip"}
_SMS_CATEGORIES = {"sms"}
_WHATSAPP_PREFIX = "channels-whatsapp-"
# Total oficial de tudo que a conta gastou (inclui custos fora dos grupos acima).
_TOTAL_CATEGORY = "totalprice"


def _resolve_group(category: str) -> Optional[str]:
    cat = category.lower()
    if cat in _VOICE_CATEGORIES:
        return "voice"
    if cat in _SMS_CATEGORIES:
        return "sms"
    if cat.startswith(_WHATSAPP_PREFIX):
        return "whatsapp"
    return None


async def _fetch_balance(account_sid: str, auth_token: str) -> dict:
    url = f"{_TWILIO_BASE}/Accounts/{account_sid}/Balance.json"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, auth=(account_sid, auth_token), timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
    return {
        "amount": round(float(data["balance"]), 4),
        "currency": data["currency"],
    }


async def _fetch_daily_records(
    account_sid: str,
    auth_token: str,
    start_date: date,
    end_date: date,
) -> list[dict]:
    url = f"{_TWILIO_BASE}/Accounts/{account_sid}/Usage/Records/Daily.json"
    params: Optional[dict] = {
        "StartDate": start_date.isoformat(),
        "EndDate": end_date.isoformat(),
        "PageSize": 1000,
    }
    records: list[dict] = []

    async with httpx.AsyncClient() as client:
        while url:
            resp = await client.get(
                url,
                auth=(account_sid, auth_token),
                params=params,
                timeout=15.0,
            )
            resp.raise_for_status()
            body = resp.json()
            records.extend(body.get("usage_records", []))

            next_uri = body.get("next_page_uri")
            if next_uri:
                url = f"https://api.twilio.com{next_uri}"
                params = None
            else:
                url = None  # type: ignore[assignment]

    return records


def _aggregate(records: list[dict]) -> tuple[dict, list[dict]]:
    """Agrega registros por categoria e por dia.

    Returns:
        costs: {"voice": float, "sms": float, "whatsapp": float, "total": float}
        daily_usage: [{"date": str, "voice": float, "sms": float, "whatsapp": float}]
    """
    costs: dict[str, float] = {"voice": 0.0, "sms": 0.0, "whatsapp": 0.0}
    total_price: Optional[float] = None
    daily: dict[str, dict[str, float]] = defaultdict(
        lambda: {"voice": 0.0, "sms": 0.0, "whatsapp": 0.0}
    )

    for record in records:
        category = (record.get("category") or "").lower()
        price = abs(float(record.get("price", 0) or 0))
        if category == _TOTAL_CATEGORY:
            total_price = (total_price or 0.0) + price
            continue
        group = _resolve_group(category)
        if group is None:
            continue
        day = record.get("start_date", "")
        if not day:
            continue
        costs[group] += price
        daily[day][group] += price

    # Sem registro `totalprice` no período, o total cai para a soma dos grupos.
    costs["total"] = total_price if total_price is not None else sum(costs.values())

    daily_usage = [
        {"date": day, **{k: round(v, 4) for k, v in values.items()}}
        for day, values in sorted(daily.items())
    ]
    return {k: round(v, 4) for k, v in costs.items()}, daily_usage


async def get_twilio_usage(
    account_sid: str,
    auth_token: str,
    start_date: date,
    end_date: date,
) -> dict:
    """Retorna payload completo de uso Twilio para o dashboard."""
    cache_key = f"twilio:{account_sid}:{start_date}:{end_date}"
    cached = cache_get(cache_key, ttl=_CACHE_TTL)
    if cached is not None:
        logger.info("twilio usage: cache hit")
        return cached

    balance, records = await asyncio.gather(
        _fetch_balance(account_sid, auth_token),
        _fetch_daily_records(account_sid, auth_token, start_date, end_date),
    )

    costs, daily_usage = _aggregate(records)
    payload = {
        "provider": "twilio",
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "balance": balance,
        "costs": costs,
        "daily_usage": daily_usage,
    }

    cache_set(cache_key, payload, ttl=_CACHE_TTL)
    return payload
