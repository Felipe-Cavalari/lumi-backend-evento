"""Supabase client para persistência de leads."""
from supabase import create_client, Client
from app.config import settings

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        if not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError("SUPABASE_URL e SUPABASE_KEY não configurados")
        _client = create_client(settings.supabase_url, settings.supabase_key)
    return _client
