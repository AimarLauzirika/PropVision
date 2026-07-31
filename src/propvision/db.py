from __future__ import annotations

from os import getenv
from pathlib import Path

from dotenv import load_dotenv
from supabase import Client, create_client

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SUPABASE_URL = getenv("SUPABASE_URL")
SUPABASE_KEY = getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("No se han encontrado SUPABASE_URL y SUPABASE_KEY en el entorno")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)