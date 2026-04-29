"""
Singleton Supabase client for scrapers and loader scripts.

Reads credentials from environment variables (caller is responsible for
loading python-dotenv before the first call to get_client).
Uses the service_role key — never use this client in browser/public contexts.
"""

from __future__ import annotations

import functools
import os

from supabase import Client, create_client


@functools.lru_cache(maxsize=1)
def get_client() -> Client:
    """Return a cached Supabase client backed by the service_role key."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError(
            "Falta SUPABASE_URL o SUPABASE_SERVICE_KEY en el entorno. Revisa tu .env."
        )
    return create_client(url, key)
