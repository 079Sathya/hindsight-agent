"""The support agent (the "patient"): recall customer memories from Hindsight, answer with the LLM."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import catalog, config, hs, store
from .hs import Mem
from .llm import llm_json, render

AGENT_SYSTEM = """You are the support assistant for Lumora Cloud, a SaaS analytics platform. You answer a support rep's question about ONE customer.

You have two sources:
1. PRODUCT CATALOG — authoritative for what each plan includes.
2. CUSTOMER MEMORIES — what we know about this customer. Each memory has an ID, a date and a source.

Rules:
- Base every customer-specific fact ONLY on CUSTOMER MEMORIES. Never invent facts.
- If memories conflict, trust the most recent one.
- If the memories do not contain the answer, say you don't know.
- In used_memory_ids list ONLY the IDs of memories you relied on.

Return ONLY a JSON object:
{"answer": "<1-2 sentence answer for the support rep>", "short_answer": "<the answer in the requested SHORT ANSWER FORMAT>", "used_memory_ids": ["<id>", "..."]}"""

AGENT_USER = """PRODUCT CATALOG:
{catalog_text}

CUSTOMER: {customer_name}
CUSTOMER MEMORIES:
{memory_lines}

QUESTION: {question}
SHORT ANSWER FORMAT: {answer_format}"""

MAX_MEMORIES = 12


@dataclass
class AgentAnswer:
    customer_key: str
    question: str
    answer: str
    short_answer: str
    used_memory_ids: list[str]
    used_memories: list[Mem]     # full objects for the ids used
    shown_memories: list[Mem]    # everything recalled and shown to the LLM
    answer_id: str
    watch: list = field(default_factory=list)   # Watch findings opened after this answer (autonomy.watch)


def memory_line(m: Mem) -> str:
    return f"[{m.id}] ({m.date}) [{m.source}] {m.text}"


def answer(customer_key: str, question: str, answer_format: str | None = None, run: str = "live") -> AgentAnswer:
    tags = store.customer_tags(customer_key)
    name = catalog.customer_name(customer_key)
    mems = hs.recall(config.MAIN_BANK_ID, query=f"{name}: {question}", tags=tags)[:MAX_MEMORIES]

    data = llm_json(AGENT_SYSTEM, render(
        AGENT_USER,
        catalog_text=catalog.catalog_text(),
        customer_name=name,
        memory_lines="\n".join(memory_line(m) for m in mems) or "(none)",
        question=question,
        answer_format=answer_format or "a brief value",
    ))

    shown = {m.id: m for m in mems}
    raw_ids = data.get("used_memory_ids") or []
    if not isinstance(raw_ids, list):
        raw_ids = [raw_ids]
    used_ids: list[str] = []
    for i in raw_ids:
        i = str(i).strip().strip("[]")
        if i in shown and i not in used_ids:   # drop hallucinated ids
            used_ids.append(i)

    text = str(data.get("answer") or "")
    short = str(data.get("short_answer") or "")
    answer_id = store.log_answer({
        "run": run,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "customer_key": customer_key,
        "question": question,
        "answer_format": answer_format,
        "answer": text,
        "short_answer": short,
        "used_memory_ids": used_ids,
    })
    ans = AgentAnswer(
        customer_key=customer_key,
        question=question,
        answer=text,
        short_answer=short,
        used_memory_ids=used_ids,
        used_memories=[shown[i] for i in used_ids],
        shown_memories=mems,
        answer_id=answer_id,
    )
    if run == "live" and config.MEMORY_ENABLED:
        # Watch: run the learned detection rules as cheap checks on what was just recalled (no LLM call unless a
        # rule fires). Only for live answers, never for eval, verification or re-asks.
        try:
            from . import autonomy
            ans.watch = autonomy.watch(ans)
        except Exception as e:  # watching must never break answering
            print(f"[agent] watch failed: {e}", flush=True)
    return ans


def _main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit('Usage: python -m memsre.agent <customer_key> "<question>" ["<answer format>"]')
    config.check()
    ans = answer(argv[0], argv[1], argv[2] if len(argv) > 2 else None)
    print(f"\nANSWER:       {ans.answer}")
    print(f"SHORT ANSWER: {ans.short_answer}")
    print(f"ANSWER ID:    {ans.answer_id}")
    print(f"\nUSED MEMORIES ({len(ans.used_memories)} of {len(ans.shown_memories)} shown):")
    for m in ans.used_memories:
        print(f"  {memory_line(m)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    _main(sys.argv[1:])
