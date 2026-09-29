"""Investigator tools: thin wrappers over hs / store / diagnose, each with an argument schema.

Every tool returns a short text summary for the agent's transcript; tools that surface memories register them
in the context so the final verdict can only cite memories the agent actually saw."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from . import catalog, config, diagnose, hs, store
from .hs import Mem

SIGNAL_PATTERNS = {
    "email_domain": re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)"),
    "email_address": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "phone": re.compile(r"\+?\d[\d -]{8,}\d"),
    "account_id": re.compile(r"\b[A-Z]{2,5}-\d{4,}\b"),
}
SIGNAL_TYPES = [*SIGNAL_PATTERNS, "keyword"]
RESULT_LINES = 10
TEXT_CHARS = 170


class ToolError(Exception):
    """A tool was called correctly but could not do its job (e.g. an unknown customer)."""


@dataclass
class Ctx:
    """Everything one investigation has gathered so far."""
    customer_key: str | None = None
    memory: bool = True                                   # False = lessons / playbooks / rules disabled
    seen: dict[str, Mem] = field(default_factory=dict)    # memories the agent has been shown, by id
    compares: dict[tuple[str, str], dict] = field(default_factory=dict)
    proposed_fix: dict | None = None
    lessons_block: str = ""                               # learned rules + rejected patterns, for identity checks
    rejected_values: set[str] = field(default_factory=set)
    llm_calls: int = 0                                    # LLM calls made inside tools (identity checks)
    used_tools: list[str] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    signature: str
    description: str
    args: dict[str, type]
    fn: Callable[..., str]


def extract_signals(text: str, signal_type: str) -> set[str]:
    """Concrete values of one signal type found in text (lower-cased), e.g. email domains."""
    rx = SIGNAL_PATTERNS.get(signal_type)
    if rx is None:
        return set()
    values = {(m.group(1) if rx.groups else m.group(0)) for m in rx.finditer(text or "")}
    if signal_type == "phone":
        values = {re.sub(r"\D", "", v) for v in values}
    return {v.lower().rstrip(".") for v in values if v}


def customer_key(ref: str) -> str:
    """Accept 'kestrel', 'customer:kestrel' or a display name."""
    ref = str(ref).strip()
    key = ref.split(":", 1)[1] if ref.startswith("customer:") else ref
    known = {t.split(":", 1)[1] for t in store.get_tag_names()} | {c["key"] for c in catalog.load_customers()}
    if key in known:
        return key
    by_name = {v.lower(): t.split(":", 1)[1] for t, v in store.get_tag_names().items()}
    by_name.update({c["name"].lower(): c["key"] for c in catalog.load_customers()})
    if ref.lower() in by_name:
        return by_name[ref.lower()]
    raise ToolError(f"unknown customer '{ref}'; call list_customer_tags to see valid tags")


def _ctags(m: Mem) -> list[str]:
    return [t for t in m.tags if t.startswith("customer:")]


def mem_line(m: Mem) -> str:
    text = m.text if len(m.text) <= TEXT_CHARS else m.text[:TEXT_CHARS] + "…"
    return f"[{m.id}] ({m.date or 'no date'}) [{', '.join(_ctags(m)) or 'no customer tag'}] {text}"


def _register(ctx: Ctx, mems: list[Mem]) -> str:
    for m in mems:
        ctx.seen[m.id] = m
    return "\n".join(mem_line(m) for m in mems[:RESULT_LINES]) or "(no memories found)"


def _mem_from_item(d: dict) -> Mem:
    tags = list(d.get("tags") or [])
    return Mem(id=d["id"], text=d.get("text") or "", date=(d.get("occurred_start") or d.get("mentioned_at") or "")[:10],
               tags=tags, source=next((t.split(":", 1)[1] for t in tags if t.startswith("source:")), ""),
               document_id=d.get("document_id"))


# --- tool implementations ------------------------------------------------------------------------

def recall_customer(ctx: Ctx, customer: str, query: str) -> str:
    key = customer_key(customer)
    mems = hs.recall(config.MAIN_BANK_ID, f"{catalog.customer_name(key)}: {query}", tags=store.customer_tags(key))
    return _register(ctx, mems[:RESULT_LINES])


def recall_whole_bank(ctx: Ctx, query: str) -> str:
    mems = hs.recall(config.MAIN_BANK_ID, query)[:12]
    if not ctx.customer_key:
        return _register(ctx, mems)
    own = set(store.customer_tags(ctx.customer_key))
    mine = [m for m in mems if set(_ctags(m)) & own]
    others = [m for m in mems if not set(_ctags(m)) & own]
    _register(ctx, mems)
    return ("THIS CUSTOMER'S RECORDS:\n" + ("\n".join(mem_line(m) for m in mine[:6]) or "(none)") +
            "\nRECORDS FILED UNDER OTHER CUSTOMER TAGS:\n" + ("\n".join(mem_line(m) for m in others[:8]) or "(none)"))


def get_memory(ctx: Ctx, id: str) -> str:
    m = ctx.seen.get(id) or hs.get_memory(config.MAIN_BANK_ID, id)
    if m is None:
        raise ToolError(f"no memory with id {id}")
    ctx.seen[m.id] = m
    return f"[{m.id}] ({m.date or 'no date'}) [tags: {', '.join(m.tags)}] {m.text}"


def list_customer_tags(ctx: Ctx) -> str:
    lines = []
    for tag in sorted(hs.list_tags(config.MAIN_BANK_ID, "customer:*")):
        key = tag.split(":", 1)[1]
        links = store.get_alias_keys(key)
        lines.append(f"{tag} = {catalog.customer_name(key)}" + (f" (linked with: {', '.join(links)})" if links else ""))
    return "\n".join(lines) or "(no customer tags)"


def find_records_sharing(ctx: Ctx, signal_type: str, value: str) -> str:
    """Generic: which customers' records contain this concrete signal value."""
    if signal_type not in SIGNAL_TYPES:
        raise ToolError(f"signal_type must be one of {', '.join(SIGNAL_TYPES)}")
    value = value.strip().lower().lstrip("@")
    if value in ctx.rejected_values:
        return (f"REJECTED PATTERN: a human reviewer rejected {signal_type} '{value}' as linking evidence. "
                "Do not use it to link records.")
    hits = [_mem_from_item(d) for d in hs.list_memories(config.MAIN_BANK_ID, q=value, limit=60)
            if d.get("fact_type") in ("world", "experience")]
    if signal_type != "keyword":
        hits = [m for m in hits if value in extract_signals(m.text, signal_type)]
    by_tag: dict[str, list[Mem]] = {}
    for m in hits:
        for t in _ctags(m) or ["(no customer tag)"]:
            by_tag.setdefault(t, []).append(m)
    for ms in by_tag.values():
        for m in ms:
            ctx.seen[m.id] = m
    if not by_tag:
        return f"no records contain {signal_type} '{value}'"
    return "\n".join(
        f"{t} ({catalog.customer_name(t.split(':', 1)[1]) if t.startswith('customer:') else '-'}): {len(ms)} record(s), "
        f"e.g. {mem_line(ms[0])}" for t, ms in by_tag.items())


def compare_records(ctx: Ctx, tag_a: str, tag_b: str) -> str:
    a, b = customer_key(tag_a), customer_key(tag_b)
    if a == b:
        raise ToolError("tag_a and tag_b are the same customer record")
    res = diagnose.identity_check(a, b, lessons_block=ctx.lessons_block)
    ctx.llm_calls += 1
    ctx.compares[(a, b)] = res
    return (f"same_customer={res['same_customer']} confidence={res['confidence']:.2f} "
            f"linking_evidence: {res['linking_evidence'] or '-'} | reason: {res['reason']}")


def recall_lessons(ctx: Ctx, query: str) -> str:
    if not ctx.memory:
        return "(memory is disabled: no lessons available)"
    mems = hs.recall(config.LESSONS_BANK_ID, query, types=("world", "experience", "observation"))[:6]
    return "\n".join(f"- {m.text}" for m in mems) or "(no lessons yet)"


def get_playbook(ctx: Ctx) -> str:
    if not ctx.memory:
        return "(memory is disabled: no playbook available)"
    from . import lessons   # lazy: lessons imports repair, which imports this module's users
    pb = lessons.playbook()
    return pb["content"] if pb and pb.get("content") else "(no playbook yet: no incident has been verified)"


def blast_radius(ctx: Ctx, memory_ids: list) -> str:
    rows = store.answers_using([str(i) for i in memory_ids])
    return f"{len(rows)} logged answer(s) used these memories: {', '.join(r['answer_id'] for r in rows) or '-'}"


def propose_fix(ctx: Ctx, type: str, actions: list) -> str:
    ftype = str(type).strip().upper()
    if ftype not in diagnose.FAILURE_TYPES:
        raise ToolError(f"type must be one of {', '.join(diagnose.FAILURE_TYPES)}")
    ctx.proposed_fix = {"type": ftype, "actions": [str(a) for a in actions]}
    automatic = {
        "RESOLUTION": "link the two identities, retain an identity-link memory, invalidate the culprit if it states a current state",
        "FRESHNESS": "invalidate the outdated culprit memory",
        "RECALL_MISS": "retain a pinned restatement of the correct fact for this customer",
        "MISSING_KNOWLEDGE": "retain the verified correction, invalidate the culprit if it states a current state",
    }.get(ftype, "no automatic memory fix (reported only)")
    return f"recorded. The automatic, reversible repair for {ftype} would: {automatic}."


REGISTRY: dict[str, Tool] = {t.name: t for t in [
    Tool("recall_customer", "recall_customer(customer, query)",
         "search one customer's memories (and linked identities); customer = key or customer:* tag",
         {"customer": str, "query": str}, recall_customer),
    Tool("recall_whole_bank", "recall_whole_bank(query)",
         "search ALL customers' memories with no customer filter; results show each memory's customer tags",
         {"query": str}, recall_whole_bank),
    Tool("get_memory", "get_memory(id)", "the full text and tags of one memory", {"id": str}, get_memory),
    Tool("list_customer_tags", "list_customer_tags()",
         "every customer:* record in the bank, its display name and existing links", {}, list_customer_tags),
    Tool("find_records_sharing", "find_records_sharing(signal_type, value)",
         f"which customers' records contain a concrete signal; signal_type is one of {', '.join(SIGNAL_TYPES)}",
         {"signal_type": str, "value": str}, find_records_sharing),
    Tool("compare_records", "compare_records(tag_a, tag_b)",
         "identity check: are two customer records the same real-world customer? (same_customer, confidence, evidence)",
         {"tag_a": str, "tag_b": str}, compare_records),
    Tool("recall_lessons", "recall_lessons(query)", "search lessons, playbooks and rules from past incidents",
         {"query": str}, recall_lessons),
    Tool("get_playbook", "get_playbook()", "the living Memory SRE playbook learned from verified incidents",
         {}, get_playbook),
    Tool("blast_radius", "blast_radius(memory_ids)", "how many logged answers used these memories",
         {"memory_ids": list}, blast_radius),
    Tool("propose_fix", "propose_fix(type, actions)",
         "record the fix you intend (a failure type and planned actions); returns what the automatic repair does",
         {"type": str, "actions": list}, propose_fix),
]}


def validate_action(action) -> tuple[Tool, dict]:
    """Check an action against the registry. Raises ValueError with a message the agent can act on."""
    if not isinstance(action, dict):
        raise ValueError('"action" must be an object like {"tool": "...", "args": {...}}')
    name = action.get("tool")
    tool = REGISTRY.get(name)
    if tool is None:
        raise ValueError(f"unknown tool '{name}'. Valid tools: {', '.join(REGISTRY)}")
    args = action.get("args", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ValueError(f"args for {name} must be an object")
    missing = [a for a in tool.args if a not in args]
    extra = [a for a in args if a not in tool.args]
    if missing or extra:
        raise ValueError(f"{tool.signature}: missing {missing or '-'}, unexpected {extra or '-'}")
    clean = {}
    for a, typ in tool.args.items():
        v = args[a]
        if typ is list:
            v = v if isinstance(v, list) else [v]
            if not all(isinstance(x, (str, int)) for x in v):
                raise ValueError(f"{name}.{a} must be a list of strings")
        elif not isinstance(v, str) or not v.strip():
            raise ValueError(f"{name}.{a} must be a non-empty string")
        clean[a] = v
    return tool, clean


def run_tool(ctx: Ctx, tool: Tool, args: dict) -> str:
    """Execute a validated tool. Tool-level problems come back as text the agent can react to."""
    try:
        return tool.fn(ctx, **args)
    except ToolError as e:
        return f"TOOL ERROR: {e}"
    except Exception as e:  # a backend hiccup must not kill the investigation
        return f"TOOL ERROR ({type(e).__name__}): {str(e)[:200]}"


def tool_catalog() -> str:
    return "\n".join(f"- {t.signature}: {t.description}" for t in REGISTRY.values())
