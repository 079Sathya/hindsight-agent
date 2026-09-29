"""Hindsight client + REST helpers."""
from __future__ import annotations

import asyncio
import atexit
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

import aiohttp
import httpx
from hindsight_client import Hindsight
from hindsight_client_api.exceptions import ApiException

from . import config


class HindsightError(RuntimeError):
    """A Hindsight REST call returned an error status."""


@dataclass
class Mem:
    id: str
    text: str
    date: str          # YYYY-MM-DD from occurred_start, else mentioned_at, else ""
    tags: list[str]
    source: str        # metadata["source"] if present, else tag "source:*" value, else ""
    document_id: str | None = None

    def to_dict(self) -> dict:
        """The incident-schema shape: id, text, date, tags, source."""
        return {"id": self.id, "text": self.text, "date": self.date, "tags": list(self.tags), "source": self.source}

    @classmethod
    def from_dict(cls, d: dict) -> Mem:
        return cls(id=d["id"], text=d.get("text", ""), date=d.get("date", ""), tags=list(d.get("tags") or []),
                   source=d.get("source", ""), document_id=d.get("document_id"))


# One client per thread: the SDK's aiohttp session is bound to the event loop of the
# thread that first used it, and Streamlit runs scripts on different threads.
_local = threading.local()


def _close_quietly(c: Hindsight) -> None:
    try:
        c.close()
    except Exception:
        pass


def client() -> Hindsight:
    c = getattr(_local, "client", None)
    if c is None:
        c = Hindsight(base_url=config.HINDSIGHT_BASE_URL, api_key=config.HINDSIGHT_API_KEY, timeout=120.0)
        _local.client = c
        atexit.register(_close_quietly, c)
    return c


class _Transient(Exception):
    pass


def _is_network_error(e: BaseException) -> bool:
    if isinstance(e, (_Transient, httpx.TransportError, aiohttp.ClientError, asyncio.TimeoutError,
                      TimeoutError, ConnectionError)):
        return True
    return isinstance(e, ApiException) and (e.status == 429 or (e.status or 0) >= 500)


def _with_retry(fn, *args, **kwargs):
    """On a network error, retry once after 3 s, then raise."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        if not _is_network_error(e):
            raise
        time.sleep(3)
        return fn(*args, **kwargs)


def _rest(method: str, bank_id: str, path: str = "", *, params: dict | None = None,
          body: dict | None = None, ignore_404: bool = False):
    url = f"{config.HINDSIGHT_BASE_URL}/v1/default/banks/{quote(bank_id, safe='')}{path}"
    headers = {"Authorization": f"Bearer {config.HINDSIGHT_API_KEY}"}
    clean = {k: v for k, v in (params or {}).items() if v is not None}

    def go() -> httpx.Response:
        r = httpx.request(method, url, headers=headers, params=clean, json=body, timeout=120.0)
        if r.status_code == 429 or r.status_code >= 500:
            raise _Transient(f"{method} {path or '/'} -> HTTP {r.status_code}")
        return r

    try:
        r = _with_retry(go)
    except _Transient as e:
        raise HindsightError(str(e)) from None
    if ignore_404 and r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise HindsightError(f"{method} {path or '/'} -> HTTP {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else None


def _to_mem(r) -> Mem:
    tags = list(r.tags or [])
    source = (r.metadata or {}).get("source") or next(
        (t.split(":", 1)[1] for t in tags if t.startswith("source:")), "")
    return Mem(id=r.id, text=r.text, date=(r.occurred_start or r.mentioned_at or "")[:10],
               tags=tags, source=source, document_id=r.document_id)


def reset_bank(bank_id: str, name: str, retain_mission: str) -> None:
    """Empty the bank in place (every document, then any remaining memories), then create/update its profile.

    Deliberately not "delete the bank, then create it": after Hindsight Cloud deletes and re-creates a bank
    under the same id, some of its servers keep answering recall from the deleted bank (measured: 6 of 10
    identical recalls returned only the old bank's memories, for about 20 minutes). Emptying in place keeps
    the bank's identity; the brief lag that remains after bulk writes is handled by wait_for_consistent_recall."""
    doc_ids: list[str] = []
    while True:
        page = _rest("GET", bank_id, "/documents", params={"limit": 100, "offset": len(doc_ids)}, ignore_404=True)
        items = (page or {}).get("items") or []
        doc_ids += [d["id"] for d in items]
        if not items or len(doc_ids) >= (page or {}).get("total", 0):
            break
    for doc_id in doc_ids:
        delete_document(bank_id, doc_id)
    _rest("DELETE", bank_id, "/memories", ignore_404=True)
    _with_retry(client().create_bank, bank_id=bank_id, name=name, retain_mission=retain_mission)


def retain_event(bank_id, content, date_iso, context, document_id, tags, metadata) -> None:
    """Synchronous retain. date_iso is YYYY-MM-DD; stored as 10:00 UTC that day."""
    y, m, d = (int(p) for p in date_iso[:10].split("-"))
    _with_retry(
        client().retain, bank_id,
        content=content,
        timestamp=datetime(y, m, d, 10, 0, tzinfo=timezone.utc),
        context=context,
        document_id=document_id,
        metadata={str(k): str(v) for k, v in (metadata or {}).items()},
        tags=list(tags or []),
    )


def recall(bank_id, query, tags=None, types=("world", "experience"), max_tokens=2048) -> list[Mem]:
    """Recall memories. With tags: only memories carrying one of them (any_strict). Without: whole bank."""
    kwargs = {"query": query, "types": list(types), "max_tokens": max_tokens, "budget": "mid"}
    if tags:
        kwargs.update(tags=list(tags), tags_match="any_strict")
    resp = _with_retry(client().recall, bank_id, **kwargs)
    return [_to_mem(r) for r in resp.results]


def get_memory(bank_id, memory_id) -> Mem | None:
    """One memory unit by id (None if it does not exist)."""
    d = _rest("GET", bank_id, f"/memories/{quote(memory_id, safe='')}", ignore_404=True)
    if not d:
        return None
    tags = list(d.get("tags") or [])
    source = (d.get("metadata") or {}).get("source") or next(
        (t.split(":", 1)[1] for t in tags if t.startswith("source:")), "")
    return Mem(id=d["id"], text=d.get("text") or "", date=(d.get("occurred_start") or d.get("mentioned_at") or "")[:10],
               tags=tags, source=source, document_id=d.get("document_id"))


def invalidate(bank_id, memory_id, reason) -> None:
    """Quarantine a memory (reversible with restore)."""
    _rest("PATCH", bank_id, f"/memories/{quote(memory_id, safe='')}",
          body={"state": "invalidated", "reason": reason})


def restore(bank_id, memory_id) -> None:
    _rest("PATCH", bank_id, f"/memories/{quote(memory_id, safe='')}", body={"state": "valid"})


def delete_document(bank_id, document_id) -> None:
    """Delete a retained document and its memories (ignoring 404)."""
    _rest("DELETE", bank_id, f"/documents/{quote(document_id, safe='')}", ignore_404=True)


def list_memories(bank_id, type=None, q=None, state=None, limit=100, tags=None) -> list[dict]:
    """List memory units (database-backed, so consistent right after a write, unlike recall).
    tags: only units carrying at least one of them (any_strict)."""
    params = {"type": type, "q": q, "state": state, "limit": limit, "offset": 0}
    if tags:
        params.update(tags=list(tags), tags_match="any_strict")
    data = _rest("GET", bank_id, "/memories/list", params=params)
    return list((data or {}).get("items") or [])


def list_tags(bank_id, q) -> list[str]:
    data = _rest("GET", bank_id, "/tags", params={"q": q})
    return [i["tag"] for i in (data or {}).get("items") or []]


def wait_for_consistent_recall(bank_id, timeout_s=180, probes=5, query="customer plan contact region",
                               tags=None, expect_ids=()) -> bool:
    """After writes, some Hindsight servers answer recall from stale data for a while (deleted or invalidated
    memories, or nothing). Poll until `probes` recalls in a row are non-empty, contain only currently valid
    memories and include every id in expect_ids. True if settled, False on timeout."""
    valid: set[str] = set()
    offset = 0
    while True:
        page = _rest("GET", bank_id, "/memories/list", params={"state": "valid", "limit": 100, "offset": offset}) or {}
        valid |= {i["id"] for i in page.get("items") or []}
        offset += 100
        if offset >= page.get("total", 0):
            break
    expect = set(expect_ids)
    deadline, ok = time.monotonic() + timeout_s, 0
    while ok < probes:
        ids = {m.id for m in recall(bank_id, query, tags=tags)}
        ok = ok + 1 if ids and ids <= valid and expect <= ids else 0
        if ok < probes:
            if time.monotonic() >= deadline:
                return False
            time.sleep(1 if ok else 5)
    return True


def wait_for_idle(bank_id, timeout_s=60) -> bool:
    """Poll pending/processing operations every 1 s. True once idle, False on timeout."""
    deadline = time.monotonic() + timeout_s
    while True:
        busy = any(
            ((_rest("GET", bank_id, "/operations", params={"status": s, "limit": 1}) or {}).get("operations"))
            for s in ("pending", "processing")
        )
        if not busy:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(1)
