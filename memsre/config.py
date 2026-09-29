"""Environment, constants and paths. Never print the keys loaded here."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


HINDSIGHT_BASE_URL = _env("HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io").rstrip("/")
HINDSIGHT_API_KEY = _env("HINDSIGHT_API_KEY")
GROQ_KEYS = [k.strip() for k in _env("GROQ_API_KEYS").split(",") if k.strip()] or (
    [_env("GROQ_API_KEY")] if _env("GROQ_API_KEY") else []
)
GROQ_MODEL = _env("GROQ_MODEL", "openai/gpt-oss-120b")
MAIN_BANK_ID = _env("MAIN_BANK_ID", "memsre-lumora-support")
LESSONS_BANK_ID = _env("LESSONS_BANK_ID", "memsre-lessons")
GROQ_TPM_BUDGET = int(_env("GROQ_TPM_BUDGET", "7000"))

# MEMSRE_MEMORY=off disables lessons, playbooks, detection rules and feedback (the benchmark's "memory OFF" arm).
MEMORY_ENABLED = _env("MEMSRE_MEMORY", "on").lower() not in ("off", "0", "false", "no")
# MEMSRE_FORCE_PIPELINE=1 makes diagnose.create_incident use the original fixed pipeline instead of the investigator.
FORCE_PIPELINE = _env("MEMSRE_FORCE_PIPELINE").lower() in ("1", "true", "yes")

SEED_DIR = ROOT / "data" / "seed"
# MEMSRE_STATE_DIR lets the learning benchmark run each arm with its own local state.
STATE_DIR = Path(_env("MEMSRE_STATE_DIR")) if _env("MEMSRE_STATE_DIR") else ROOT / "data" / "state"
CACHE_DIR = ROOT / "data" / "cache"
RESULTS_DIR = ROOT / "data" / "results"
DOCS_DIR = ROOT / "docs"

for _d in (SEED_DIR, STATE_DIR, CACHE_DIR, RESULTS_DIR, DOCS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def check() -> None:
    """Raise a clear error if a required key is missing (names only, never values)."""
    missing = []
    if not HINDSIGHT_API_KEY:
        missing.append("HINDSIGHT_API_KEY")
    if not GROQ_KEYS:
        missing.append("GROQ_API_KEY (or GROQ_API_KEYS)")
    if missing:
        raise RuntimeError(
            f"Missing required setting(s) in .env: {', '.join(missing)}. "
            "Copy .env.example to .env and fill them in."
        )
