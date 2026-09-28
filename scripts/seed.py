"""Build a fresh demo memory bank from data/seed/events.jsonl.  Usage: python scripts/seed.py [--keep-lessons]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(errors="replace")

from memsre import catalog, config, hs, store  # noqa: E402

MAIN_RETAIN_MISSION = (
    "Extract facts about customers of Lumora Cloud: plans and plan changes with effective dates, hosting regions, "
    "contacts and their email addresses, billing events, and support requests. "
    "Keep company and person names exactly as written."
)
LESSONS_RETAIN_MISSION = "Extract lessons about how AI agent memory failed: the failure type, the detection signal, and the fix."


def seed(keep_lessons: bool = False) -> int:
    """Reset the bank(s), retain every seed event, reset local state. Returns the number of events."""
    config.check()
    hs.reset_bank(config.MAIN_BANK_ID, name="Lumora Support Memory", retain_mission=MAIN_RETAIN_MISSION)
    if not keep_lessons:
        hs.reset_bank(config.LESSONS_BANK_ID, name="Memory SRE Lessons", retain_mission=LESSONS_RETAIN_MISSION)

    events = catalog.load_events()
    for k, ev in enumerate(events, 1):
        hs.retain_event(
            config.MAIN_BANK_ID,
            content=ev["content"],
            date_iso=ev["date"],
            context=f"{ev['source']} record for {ev['customer_name']}",
            document_id=ev["id"],
            tags=[f"customer:{ev['customer_key']}", f"source:{ev['source']}"],
            metadata={"source": ev["source"], "event_id": ev["id"], "customer_name": ev["customer_name"]},
        )
        print(f"{k}/{len(events)}  {ev['id']}", flush=True)

    tag_names = {f"customer:{ev['customer_key']}": ev["customer_name"] for ev in events}
    store.set_tag_names(tag_names)
    store.reset_state()
    store.set_tag_names(tag_names)

    hs.wait_for_idle(config.MAIN_BANK_ID, 300)
    print(f"SEEDED {len(events)} events", flush=True)
    return len(events)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-lessons", action="store_true", help="do not reset the lessons bank")
    seed(keep_lessons=parser.parse_args().keep_lessons)
