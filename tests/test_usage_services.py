"""Testes da agregação de custos (Twilio e ElevenLabs)."""
from datetime import date, datetime, timezone

from app.services.elevenlabs_usage_service import _aggregate_conversations
from app.services.twilio_service import _aggregate


def test_twilio_nao_soma_categorias_sobrepostas():
    """`calls` já contém `calls-inbound` e `calls-inbound-local`."""
    records = [
        {"category": "calls", "price": "-10.00", "start_date": "2026-09-01"},
        {"category": "calls-inbound", "price": "-6.00", "start_date": "2026-09-01"},
        {"category": "calls-inbound-local", "price": "-6.00", "start_date": "2026-09-01"},
        {"category": "calls-outbound", "price": "-4.00", "start_date": "2026-09-01"},
        {"category": "calls-client", "price": "-1.00", "start_date": "2026-09-01"},
        {"category": "sms", "price": "-2.00", "start_date": "2026-09-01"},
        {"category": "sms-outbound", "price": "-2.00", "start_date": "2026-09-01"},
        {"category": "channels-whatsapp-service", "price": "-0.50", "start_date": "2026-09-01"},
        {"category": "channels-whatsapp-template-marketing", "price": "-0.25", "start_date": "2026-09-02"},
        {"category": "totalprice", "price": "-14.00", "start_date": "2026-09-01"},
    ]
    costs, daily = _aggregate(records)
    assert costs == {"voice": 11.0, "sms": 2.0, "whatsapp": 0.75, "total": 14.0}
    assert daily == [
        {"date": "2026-09-01", "voice": 11.0, "sms": 2.0, "whatsapp": 0.5},
        {"date": "2026-09-02", "voice": 0.0, "sms": 0.0, "whatsapp": 0.25},
    ]


def test_twilio_total_sem_totalprice_soma_os_grupos():
    records = [
        {"category": "calls", "price": "-3.00", "start_date": "2026-09-01"},
        {"category": "sms", "price": "-1.50", "start_date": "2026-09-01"},
    ]
    costs, _ = _aggregate(records)
    assert costs["total"] == 4.5


def _ts(y, m, d, h=12):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp())


def test_elevenlabs_agrega_minutos_por_dia():
    conversations = [
        {"start_time_unix_secs": _ts(2026, 9, 1), "call_duration_secs": 90},
        {"start_time_unix_secs": _ts(2026, 9, 1), "call_duration_secs": 30},
        {"start_time_unix_secs": _ts(2026, 9, 2), "call_duration_secs": 300},
        # fora do período: ignorada
        {"start_time_unix_secs": _ts(2026, 8, 31), "call_duration_secs": 600},
        # sem timestamp: ignorada
        {"call_duration_secs": 999},
    ]
    result = _aggregate_conversations(
        conversations, date(2026, 9, 1), date(2026, 9, 2), cost_per_minute=0.10
    )
    assert result["total_conversations"] == 3
    assert result["total_minutes"] == 7.0
    assert result["cost"] == 0.7
    assert result["daily_usage"] == [
        {"date": "2026-09-01", "conversations": 2, "minutes": 2.0, "cost": 0.2},
        {"date": "2026-09-02", "conversations": 1, "minutes": 5.0, "cost": 0.5},
    ]
