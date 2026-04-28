from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")

def _key(*vars: str) -> str | None:
    for v in vars:
        val = os.getenv(v, "").strip()
        if val and not val.startswith("your_"):
            return val
    return None

# ── LLM ──────────────────────────────────────────────────────────
OPENAI_API_KEY = _key("OPENAI_API_KEY")
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o").strip()

GROQ_KEY   = _key("GROQ_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct").strip()

# ── APIs ─────────────────────────────────────────────────────────
SEMANTIC_SCHOLAR_KEY = _key("SEMANTIC_SCHOLAR_KEY")
NCBI_API_KEY         = _key("NCBI_API_KEY")
UNPAYWALL_EMAIL      = os.getenv("UNPAYWALL_EMAIL", "").strip()

# ── Paths ─────────────────────────────────────────────────────────
DATA_DIR    = _ROOT / "data"
MOF_DB_PATH = Path(os.getenv("MOF_DB_PATH") or DATA_DIR / "databases" / "mof.sqlite3")
VECTOR_PATH = Path(os.getenv("VECTOR_DB_PATH") or DATA_DIR / "vectors")
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR") or DATA_DIR / "uploads")

for _p in (MOF_DB_PATH.parent, VECTOR_PATH, UPLOADS_DIR):
    _p.mkdir(parents=True, exist_ok=True)

USER_AGENT = "mof-discovery/1.0 (academic prototype)"
