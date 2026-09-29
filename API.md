# Memory SRE backend API (for `app.py`)

Everything `app.py` needs is below. The UI should call only these functions and keep business logic out of `app.py` (BUILD_PLAN §12). Spec sections are in brackets.

## Ground rules

- **Imports:** `from memsre import agent, catalog, config, diagnose, lessons, repair, store`.
- **Everything is synchronous and blocking.** Timings measured on Groq's free tier: `agent.answer` 1–5 s; `diagnose.create_incident` 15–25 s; `repair.apply_fix` 30–90 s; `lessons.proactive_identity_scan` about 15 s. Run each call inside `st.spinner(...)`. The Groq limiter may add waits under load (you'll see `[llm] ...` lines in the terminal).
- **Repairs wait for Hindsight.** `apply_fix`, `undo_fix` and `accept_proposal` only return once that customer's recall reflects the change (at most 90 s). Some Hindsight Cloud servers lag behind writes, and without this wait an immediate **Re-ask** could read stale memory.
- **Groq quota.** The free tier allows 200k tokens per day per Groq *organization*. One `scripts/eval.py` run uses about 80k, and a live demo about 15k. With two keys from different Groq accounts in `GROQ_API_KEYS=key1,key2`, a key that hits its limit is skipped automatically.
- **LLM cache.** Identical prompts are answered from `data/cache/llm_cache.json`, so repeating a demo step on an unchanged bank is instant and free.
- **Reset** is done in a terminal with `python scripts/seed.py`, not from the UI [§12 sidebar note]. It takes about 3–4 minutes, plus up to 30 minutes waiting for Hindsight recall to settle; it prints `still settling` while it waits. Start recording only after it prints `SEEDED 34 events`.
- **Errors.** Every function raises an exception whose `str(e)` is readable, so wrap each call in `try/except Exception as e: st.error(str(e))` [§12].
  | Exception | When |
  |---|---|
  | `RuntimeError` | `config.check()`: a key is missing from `.env` |
  | `ValueError` | invalid action for an incident's state or type (for example, fixing an EXECUTION incident, or undoing an incident that isn't fixed) |
  | `memsre.llm.LLMError` | Groq failed after retries, or returned invalid JSON after a re-ask |
  | `memsre.hs.HindsightError` | a Hindsight REST call returned an error |
- **Threads.** Safe to call from Streamlit's script threads. The Hindsight client is one per thread, because its aiohttp session is tied to that thread's event loop.
- **Secrets.** `config.HINDSIGHT_API_KEY` and `config.GROQ_KEYS` exist, but never render them. Nothing in the backend prints them.

## `memsre.config`

| Name | Type | Purpose |
|---|---|---|
| `MAIN_BANK_ID` | `str` | Customer-memory bank id (sidebar) |
| `LESSONS_BANK_ID` | `str` | Lessons bank id (sidebar) |
| `DOCS_DIR / "before_after.png"` | `Path` | Chart written by `scripts/eval.py` (Memory Health tab) |
| `check() -> None` | function | Raises `RuntimeError` naming the missing `.env` setting. Call once at startup. |

## `memsre.catalog`

| Signature | Returns | Purpose |
|---|---|---|
| `load_customers() -> list[dict]` | `[{"key": "kestrel", "name": "Kestrel Logistics"}, ...]` | Customer selectbox (CRM names only) |
| `load_questions() -> list[dict]` | `[{"id", "customer", "question", "format", "accepted", "defect", "correction"}, ...]` | Sample-question buttons: filter by `q["customer"] == key` and take the first 4 |
| `customer_name(key: str) -> str` | display name | Any customer key to a name, including billing-only keys such as `"anvaya"` |

## `memsre.agent`

| Signature | Returns | Purpose |
|---|---|---|
| `answer(customer_key: str, question: str, answer_format: str \| None = None, run: str = "live") -> AgentAnswer` | `AgentAnswer` | Ask the support agent. The answer is logged automatically, so 👍 needs no backend call. |

`AgentAnswer` is a dataclass. It is fine to keep in `st.session_state["last_answer"]`:

| Field | Type | Notes |
|---|---|---|
| `customer_key` | `str` | |
| `question` | `str` | |
| `answer` | `str` | 1–2 sentence answer for the rep |
| `short_answer` | `str` | e.g. `"Yes"`, `"growth"`, `"1000"`; `""` if the model gave none |
| `used_memory_ids` | `list[str]` | |
| `used_memories` | `list[Mem]` | The "Memories used" table |
| `shown_memories` | `list[Mem]` | Everything recalled and shown to the LLM (up to 12) |
| `answer_id` | `str` | `"ANS-0001"`, ... |

`Mem` (in `memsre.hs`) is a dataclass with `id`, `text`, `date` (`"YYYY-MM-DD"` or `""`), `tags` (`list[str]`), `source` (e.g. `"crm_notes"`) and `document_id`. For the table's short id, use `m.id[:8]`.

## `memsre.diagnose`

| Signature | Returns | Purpose |
|---|---|---|
| `create_incident(ans: AgentAnswer, correction: str, answer_format: str \| None = None) -> dict` | incident dict (below) | 👎 **Report & diagnose**. Saves the incident; use `inc["id"]` and `inc["failure_type"]` in the success message. |
| `FAILURE_TYPES` | `list[str]` | `["RESOLUTION", "FRESHNESS", "RECALL_MISS", "EXECUTION", "MISSING_KNOWLEDGE", "UNKNOWN"]` |
| `NO_FIX_TYPES` | `tuple[str, ...]` | `("EXECUTION", "UNKNOWN")`: disable **Apply fix** for these |

### Incident dict [§9.3]

Plain JSON (strings, numbers, bools, lists, dicts, `None`), safe for `st.session_state`.

| Key | Type | Notes |
|---|---|---|
| `id` | `str` | `"INC-001"`, ... |
| `created_at` | `str` | ISO timestamp, UTC |
| `status` | `str` | `"open"`, `"fixed"`, `"reverted"`, `"no_fix"` (EXECUTION/UNKNOWN) or `"prevented"` (from the proactive scan) |
| `customer_key`, `customer_name` | `str` | |
| `question` | `str \| None` | `None` for `prevented` incidents |
| `answer_format` | `str \| None` | |
| `wrong_answer`, `wrong_short_answer`, `correction` | `str \| None` | `None` for `prevented` incidents |
| `used_memories`, `culprits`, `supporting` | `list[dict]` | Each item is `{"id", "text", "date", "tags", "source"}` |
| `wrong_claim` | `str` | "Wrong claim" line |
| `culprit_asserts_current_state` | `bool` | |
| `culprit_reason`, `evidence_reason` | `str` | LLM one-liners (extra keys, optional to show) |
| `identity` | `dict \| None` | `{"foreign_tag": "customer:anvaya", "foreign_name", "same_customer", "confidence", "linking_evidence", "reason"}`. `None` when no identity check ran. |
| `failure_type` | `str` | One of `FAILURE_TYPES` |
| `root_cause` | `str` | For `st.warning(...)` |
| `blast_radius` | `dict` | `{"answers_affected": int, "answer_ids": [str]}`, for `st.metric("Earlier answers that used this memory", ...)` |
| `recommended_fix` | `list[str]` | Bullet list |
| `applied_actions` | `list[dict]` | Filled by `apply_fix`. See "Applied actions" below. |
| `reask` | `dict \| None` | Set by `repair.reask`: `{"answer", "short_answer", "used_memory_ids", "used_memories"}`. Cleared by `apply_fix` and `undo_fix`. |

**Highlighting the foreign tag** (Contradicting-evidence section): a tag in `supporting[i]["tags"]` is foreign when it equals `incident["identity"]["foreign_tag"]`. More generally, it is foreign when it starts with `customer:` and isn't `"customer:" + customer_key`.

**Identity line:** `f"{inc['customer_name']} ≡ {inc['identity']['foreign_name']} · confidence {inc['identity']['confidence']:.2f}"`, plus `inc["identity"]["linking_evidence"]`.

**Applied actions**, each one a dict:

| `kind` | Other keys | Suggested display |
|---|---|---|
| `"alias"` | `a`, `b` (customer keys) | `Linked identities: {a} ≡ {b}` |
| `"retain_doc"` | `bank`, `document_id` | `Retained in Hindsight: {document_id}` |
| `"invalidate"` | `bank`, `memory_id` | `Invalidated in Hindsight: {memory_id} (reversible)` [§12] |

## `memsre.repair`

| Signature | Returns | Purpose |
|---|---|---|
| `apply_fix(incident_id: str) -> dict` | updated incident, `status == "fixed"` | **Apply fix**. Raises `ValueError` for EXECUTION/UNKNOWN. Works from `open` or `reverted`; calling it again on a `fixed` incident is a no-op. Also records a lesson (Tier 3). If a Hindsight call fails partway, the actions already taken are rolled back, the incident stays `open`, and the error is raised. |
| `undo_fix(incident_id: str) -> dict` | updated incident, `status == "reverted"` | **Undo fix**. Reverses every applied action in Hindsight and local state. Raises `ValueError` unless the status is `fixed`. If some action can't be reversed, raises `RuntimeError`; retrying is safe. |
| `reask(incident_id: str) -> dict` | updated incident with `incident["reask"]` set | **Re-ask question**. Raises `ValueError` if `question` is `None`. |

Button rules [§12]:
- **Apply fix** is enabled when `status == "open"` and `failure_type not in NO_FIX_TYPES`.
- **Undo fix** is enabled when `status == "fixed"`.
- **Re-ask** is enabled when `status == "fixed"` and `question is not None`.
- **After re-ask:** show `st.success` when `normalize(reask["short_answer"]) != normalize(wrong_short_answer)`, using `normalize` from `memsre.grading`.

## `memsre.store`

| Signature | Returns | Purpose |
|---|---|---|
| `list_incidents() -> list[dict]` | incidents, **newest first** | Incidents selectbox: `f"{i['id']} · {i['failure_type']} · {i['customer_name']} · {i['status']}"` |
| `get_incident(incident_id: str) -> dict \| None` | incident, or `None` | Reload the selected incident after an action |
| `alias_pairs() -> list[tuple[str, str]]` | e.g. `[("anvaya", "kestrel")]` | Sidebar "linked identities" count: `len(...)` |
| `list_answers() -> list[dict]` | answer log records, oldest first | Sidebar "answers logged" count: `len(...)` |
| `load_eval_results() -> dict \| None` | `eval_latest.json` (below), or `None` | Sidebar `before% → after%` and the Memory Health tab |

## `memsre.lessons` (Tier 3)

| Signature | Returns | Purpose |
|---|---|---|
| `learned(limit: int = 10) -> list[dict]` | `[{"text": str, "proof_count": int}, ...]`, e.g. `{"text": "Kestrel Logistics and Anvaya Technologies Pvt Ltd are the same customer entity.", "proof_count": 1}` | "What Memory SRE has learned" list (Hindsight's consolidated observations; empty until the first fix) |
| `has_resolution_lesson() -> bool` | | Enables **Run proactive scan**. Becomes `True` after the first RESOLUTION fix. |
| `proactive_identity_scan() -> list[dict]` | proposals (below); `[]` if none | **Run proactive scan**. Store the result in `st.session_state` so the cards survive reruns. |
| `accept_all(proposals: list[dict]) -> list[dict]` | the new `prevented` incidents | **Accept all**: accepts every proposal whose pair isn't linked yet (skips linked ones) |
| `learning_curve() -> list[dict]` | `[{"id", "customer_name", "failure_type", "status", "kind": "reactive" or "prevented", "wrong_answers": int, "lesson_learned": bool}, ...]`, oldest first | **Learning curve** chart. Built from `incidents.json` only (no LLM or Hindsight calls). `wrong_answers` is the blast radius, and 0 for prevented incidents. `lesson_learned` marks the first reactively fixed incident. |
| `accept_proposal(p: dict) -> dict` | the new incident (`status == "prevented"`) | **Link identities** on a proposal card, then `st.success("Prevented: linked before any wrong answer.")`. Raises `ValueError` if the pair is already linked (e.g. on a double click). |

Proposal dict: `{"a": "saffron", "b": "mehta-bros", "name_a": "Saffron Retail", "name_b": "Mehta Brothers Trading LLP", "confidence": 0.95, "linking_evidence": str, "shared_domain": "mehtabros.co.in", "reason": str}`. Card title: `f"{p['name_a']} ≡ {p['name_b']}"`.

## Files

- **`docs/before_after.png`**: the headline chart (`st.image`).
- **`data/results/eval_latest.json`**, as returned by `store.load_eval_results()`:
  ```jsonc
  {
    "before_accuracy": 60.0,          // percent, 0-100 (real result of the committed run)
    "after_accuracy": 100.0,          // percent, 0-100
    "n": 20,
    "questions": [{"id", "customer", "question", "defect", "before_correct", "before_short",
                   "after_correct", "after_short", "fixed_by"}],   // fixed_by: "INC-001" or null
    "incidents": [{"id", "failure_type", "customer", "answers_fixed"}],
    "by_type": {"RESOLUTION": 2}
  }
  ```
  "Wrong answers fixed" = `sum(i["answers_fixed"] for i in incidents)`. For ✓/✗ columns use `before_correct` and `after_correct`.

## What the demo produces (verified end to end from Python)

After `python scripts/seed.py`:

1. `agent.answer("kestrel", "Can Kestrel Logistics export audit logs?")` gives `short_answer "Yes"`, which is wrong.
2. `diagnose.create_incident(ans, correction)` gives `failure_type "RESOLUTION"`, with `identity.foreign_tag "customer:anvaya"`, confidence 0.95, and linking evidence quoting `ravi.k@anvaya.in` and `accounts@anvaya.in`.
3. `repair.apply_fix(id)` then `repair.reask(id)` gives `"No, … now on the Growth plan …"`. `repair.undo_fix(id)` then `repair.reask(id)` gives `"Yes"` again.
4. After that fix, `lessons.has_resolution_lesson()` is `True`, and `lessons.proactive_identity_scan()` returns three proposals: Saffron Retail ≡ Mehta Brothers Trading LLP (`mehtabros.co.in`), Monsoon Trails ≡ Ruparel Holidays Pvt Ltd (`ruparelholidays.in`) and Neelgiri Organics ≡ Kaveri Agro Foods LLP (`kaveriagro.co.in`).
5. `lessons.accept_all(proposals)`, or `accept_proposal(p)` for each, creates `prevented` incidents. Asking "Can Saffron Retail enable SSO?" then changes from "No" to "Yes", and `lessons.learning_curve()` gives wrong answers 2, 0, 0, 0.

## Tab recipes (§12)

1. **Support Console:** `catalog.load_customers()` → `agent.answer(key, q)` → show `ans.answer`, `ans.used_memories` → 👎 → `diagnose.create_incident(ans, correction)`.
2. **Incidents:** `store.list_incidents()` → `store.get_incident(id)` → `repair.apply_fix` / `repair.undo_fix` / `repair.reask` (each returns the updated incident).
3. **Memory Health:** `store.load_eval_results()` + `config.DOCS_DIR / "before_after.png"` → `lessons.learned()` → `lessons.has_resolution_lesson()` → `lessons.proactive_identity_scan()` → `lessons.accept_proposal(p)`.
