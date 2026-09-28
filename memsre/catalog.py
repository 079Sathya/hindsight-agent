"""Load catalog/customers/questions/events; render catalog text."""
from __future__ import annotations

import json

from . import config, store


def _read(name: str):
    return json.loads((config.SEED_DIR / name).read_text(encoding="utf-8"))


def load_catalog() -> dict:
    return _read("catalog.json")


def load_customers() -> list[dict]:
    return _read("customers.json")


def load_questions() -> list[dict]:
    return _read("questions.json")


def load_events() -> list[dict]:
    lines = (config.SEED_DIR / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def customer_name(key: str) -> str:
    """CRM name from customers.json, else the name recorded for its tag at seed time, else the key."""
    for c in load_customers():
        if c["key"] == key:
            return c["name"]
    return store.get_tag_names().get(f"customer:{key}", key)


def catalog_text() -> str:
    cat = load_catalog()

    def yn(v: bool) -> str:
        return "yes" if v else "no"

    lines = [
        f"{p['display']}: SSO {yn(p['sso'])}; audit log export {yn(p['audit_log_export'])}; "
        f"API rate limit {p['api_rate_limit_per_min']} requests/min; data retention {p['data_retention_days']} days; "
        f"support SLA {p['support_sla']}; dedicated CSM {yn(p['dedicated_csm'])}."
        for p in cat["plans"].values()
    ]
    lines.append("Regions: " + ", ".join(f"{code} = {name}" for code, name in cat["regions"].items()) + ".")
    return "\n".join(lines)
