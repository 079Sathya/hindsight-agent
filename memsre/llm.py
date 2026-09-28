"""Groq JSON client: disk cache, per-key rate limiter, retries, JSON repair."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
import time
from collections import deque

from openai import APIConnectionError, APIStatusError, BadRequestError, OpenAI

from . import config

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
CACHE_FILE = config.CACHE_DIR / "llm_cache.json"

_OPTIONAL_PARAMS = ("reasoning_effort", "response_format", "max_completion_tokens")
_MAX_ATTEMPTS = 5
_MIN_INTERVAL_S = 2.1
_WINDOW_S = 60.0
_NOT_JSON_NOTE = "\n\nYour previous reply was not valid JSON. Return ONLY the JSON object."
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class LLMError(RuntimeError):
    """The LLM call failed, or never produced a valid JSON object."""


_lock = threading.RLock()
_cache: dict[str, dict] | None = None
_clients: dict[str, OpenAI] = {}
_usage: dict[str, deque] = {}        # key -> deque[(monotonic time, estimated tokens)]
_last_call: dict[str, float] = {}    # key -> monotonic time of the last call
_dropped_params: set[str] = set()    # params the API rejected; remembered for the process
_next_key = 0


def _load_cache() -> dict[str, dict]:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            _cache = {}
    return _cache


def _save_cache() -> None:
    tmp = CACHE_FILE.with_name(CACHE_FILE.name + ".tmp")
    tmp.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CACHE_FILE)


def _pick_key() -> str:
    global _next_key
    with _lock:
        if not config.GROQ_KEYS:
            raise LLMError("No Groq API key configured. Set GROQ_API_KEY (or GROQ_API_KEYS) in .env.")
        key = config.GROQ_KEYS[_next_key % len(config.GROQ_KEYS)]
        _next_key += 1
        return key


def _client(key: str) -> OpenAI:
    with _lock:
        if key not in _clients:
            # max_retries=0: the retry policy below is the only one.
            _clients[key] = OpenAI(base_url=GROQ_BASE_URL, api_key=key, max_retries=0, timeout=120.0)
        return _clients[key]


def _throttle(key: str, estimate: int) -> None:
    """Block until this key has TPM budget and 2.1 s have passed since its last call."""
    while True:
        with _lock:
            now = time.monotonic()
            q = _usage.setdefault(key, deque())
            while q and now - q[0][0] >= _WINDOW_S:
                q.popleft()
            wait = 0.0
            if key in _last_call:
                wait = _MIN_INTERVAL_S - (now - _last_call[key])
            used = sum(tokens for _, tokens in q)
            if q and used + estimate > config.GROQ_TPM_BUDGET:
                expire_at = q[-1][0] + _WINDOW_S
                freed = 0
                for ts, tokens in q:
                    freed += tokens
                    if used - freed + estimate <= config.GROQ_TPM_BUDGET:
                        expire_at = ts + _WINDOW_S
                        break
                wait = max(wait, expire_at - now)
            if wait <= 0:
                q.append((now, estimate))
                _last_call[key] = now
                return
        time.sleep(wait)


def _error_text(e: APIStatusError) -> str:
    return f"{e} {json.dumps(e.body, default=str) if e.body is not None else ''}"


def _retry_after(e: APIStatusError) -> float | None:
    raw = e.response.headers.get("retry-after") if e.response is not None else None
    try:
        return max(0.0, float(raw)) if raw is not None else None
    except ValueError:
        return None


def _complete(system: str, user: str, max_completion_tokens: int) -> str:
    """One chat completion with the rate limiter and retry policy. Returns the raw content."""
    key = _pick_key()
    client = _client(key)
    estimate = (len(system) + len(user)) // 4 + 500
    attempt = 0
    while True:
        _throttle(key, estimate)
        kwargs: dict = {
            "model": config.GROQ_MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
        }
        if "response_format" not in _dropped_params:
            kwargs["response_format"] = {"type": "json_object"}
        if "max_completion_tokens" in _dropped_params:
            kwargs["max_tokens"] = max_completion_tokens
        else:
            kwargs["max_completion_tokens"] = max_completion_tokens
        if "reasoning_effort" not in _dropped_params:
            kwargs["extra_body"] = {"reasoning_effort": "low"}

        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except BadRequestError as e:
            body = e.body if isinstance(e.body, dict) else {}
            if body.get("code") == "json_validate_failed":
                # Groq's JSON mode rejected the output; hand it to the JSON repair path.
                return str(body.get("failed_generation") or "")
            text = _error_text(e)
            rejected = [p for p in _OPTIONAL_PARAMS if p in text and p not in _dropped_params]
            if not rejected:
                raise LLMError(f"Groq rejected the request (400): {text[:300]}") from e
            _dropped_params.update(rejected)
            print(f"[llm] API rejected {', '.join(rejected)}; retrying without it", flush=True)
            continue
        except APIStatusError as e:
            if e.status_code != 429 and e.status_code < 500:
                raise LLMError(f"Groq API error ({e.status_code}): {_error_text(e)[:300]}") from e
            reason, delay = f"HTTP {e.status_code}", _retry_after(e)
        except APIConnectionError as e:  # includes APITimeoutError
            reason, delay = type(e).__name__, None

        attempt += 1
        if attempt >= _MAX_ATTEMPTS:
            raise LLMError(f"Groq call failed after {_MAX_ATTEMPTS} attempts ({reason}).")
        if delay is None:
            delay = 5 * 2 ** (attempt - 1)
        print(f"[llm] {reason}; retry {attempt}/{_MAX_ATTEMPTS - 1} in {delay:.0f}s", flush=True)
        time.sleep(delay)


def _parse(content: str) -> dict | None:
    candidates = [content]
    m = _JSON_BLOCK.search(content or "")
    if m:
        candidates.append(m.group(0))
    for c in candidates:
        try:
            data = json.loads(c)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _log(source: str, user: str, start: float) -> None:
    snippet = " ".join(user[:60].split())
    print(f"[llm] {source:<5}  {snippet:<60}  {time.monotonic() - start:.1f}s", flush=True)


_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def render(template: str, **values) -> str:
    """Fill {name} placeholders in one pass, leaving literal JSON braces in the prompt untouched."""
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template)


def llm_json(system: str, user: str, *, max_completion_tokens: int = 1200) -> dict:
    """Ask the LLM for a JSON object. Cached on disk; rate-limited; retried; JSON-repaired."""
    start = time.monotonic()
    cache_key = hashlib.sha256(
        json.dumps([config.GROQ_MODEL, system, user, max_completion_tokens]).encode("utf-8")
    ).hexdigest()
    with _lock:
        hit = _load_cache().get(cache_key)
    if hit is not None:
        _log("cache", user, start)
        return copy.deepcopy(hit)

    data = _parse(_complete(system, user, max_completion_tokens))
    if data is None:
        data = _parse(_complete(system, user + _NOT_JSON_NOTE, max_completion_tokens))
    if data is None:
        raise LLMError("The model did not return a valid JSON object, even after a re-ask.")

    with _lock:
        _load_cache()[cache_key] = data
        _save_cache()
    _log("api", user, start)
    return copy.deepcopy(data)
