"""Smoke test: config, Hindsight connectivity, Groq JSON call."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(errors="replace")

from memsre import config, hs  # noqa: E402
from memsre.diagnose import SRE_SYSTEM  # noqa: E402
from memsre.llm import llm_json  # noqa: E402


def main() -> None:
    config.check()
    print("Hindsight api_version:", hs.client().get_version().api_version)
    print("LLM:", llm_json(SRE_SYSTEM, 'Return {"ok": true}'))
    print("SMOKE OK")


if __name__ == "__main__":
    main()
