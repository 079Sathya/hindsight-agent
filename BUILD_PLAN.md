# BUILD_PLAN.md — Memory SRE for Hindsight (demo build)

> **For the coding agent:** this document is the complete specification. Build it top to bottom in the order of **Section 14 (Build order)**. Do not add features that are not listed. Where this document gives exact text (data, prompts, UI copy), use it verbatim. When a step has a **CHECK**, run it and make it pass before moving on. Commit to git after every checkpoint.

---

## 0. What we are building (read first)

**Memory SRE** is a reliability tool for AI-agent memory built on **Hindsight** (vectorize.io).

When an AI support agent gives a **wrong answer**, Memory SRE works out whether **memory** caused it, and which **exact memory**. It then shows the evidence, **repairs** the memory reversibly using Hindsight's own curation API, and **proves** the agent is fixed by re-asking the question.

**Pitch line:** *"Hindsight tells you what it remembered. Memory SRE tells you whether remembering it was the mistake — and fixes it."*

### The demo story (this is the spec — everything we build serves it)

1. A fictional SaaS vendor, **Lumora Cloud**, runs a support agent. The agent remembers facts about each customer in a Hindsight memory bank.
2. The support rep asks: *"Can Kestrel Logistics export audit logs?"* The agent confidently says **"Yes — they're on Enterprise."** **This is wrong.**
3. **Why it's wrong (the hidden defect):**
   - The sales team's notes (CRM) call the customer **"Kestrel Logistics"**.
   - The billing system records the same company under its legal name, **"Anvaya Technologies Pvt Ltd"**.
   - Billing recorded a **downgrade to the Growth plan** on 1 August 2026, under the Anvaya name.
   - Memory holds both records, but nothing ever linked the two names, so the agent never sees the downgrade.
4. The rep clicks 👎 and types what the customer said. Memory SRE:
   - finds the **culprit memory** ("Kestrel signed Enterprise, June 2026");
   - finds the **contradicting evidence** stored under "Anvaya Technologies Pvt Ltd";
   - confirms they are the **same customer** from linking evidence: the admin email `ravi.k@anvaya.in`;
   - classifies the failure as **RESOLUTION** (an identity split), not a model error;
   - reports the **blast radius** (how many earlier answers used that bad memory).
5. The rep clicks **Apply fix**. The fix:
   - links the two identities;
   - invalidates the superseded memory in Hindsight (reversible);
   - records a lesson.
   Then **Re-ask** returns **"No — Growth doesn't include audit log export."**
6. **Proactive scan:** using the lesson it just learned, Memory SRE scans the rest of memory and finds a second identity split — **"Saffron Retail" = "Mehta Brothers Trading LLP"** — *before* any wrong answer happens.
7. The **Memory Health** tab shows the headline chart: accuracy on 20 support questions **before vs after** Memory SRE repairs.

### Definition of done (for tomorrow)

- [ ] `python scripts/seed.py` builds a fresh demo memory bank.
- [ ] `python scripts/eval.py` produces `data/results/eval_latest.json` and `docs/before_after.png`, with after-accuracy greater than before-accuracy.
- [ ] `streamlit run app.py` runs the full story in steps 2–7 above, without errors.
- [ ] `pytest` passes.
- [ ] The README contains the chart, the architecture and the section **"How Hindsight memory is used"**.
- [ ] No secrets in the repo, and the repo is pushed to GitHub.

---

## 1. Non-goals — DO NOT BUILD

- No authentication, users, login, Auth0 or roles.
- No deployment, Docker, cloud hosting or CI.
- No database other than Hindsight plus local JSON files.
- No Microsoft Agent Framework, Teams or Azure (these are for the finale, not tonight).
- No health "score", no continuous background monitoring and no webhooks.
- No failure types beyond the six in §9.4. Implement WRITE detection? **No.**
- No React, Next.js or custom frontend: **Streamlit only**.
- No LangChain or LlamaIndex. Call the APIs directly.

---

## 2. Tech stack and environment

- **OS:** Windows 10/11, PowerShell. The repo already exists: `hindsight-agent/` with a Python `venv/`, `.gitignore` (Python template) and `README.md`.
- **Python** 3.10+ (use `from __future__ import annotations` at the top of every module).
- **Memory:** Hindsight Cloud. Base URL `https://api.hindsight.vectorize.io`, API key in `.env`.
- **LLM:** Groq (OpenAI-compatible API) via the `openai` Python SDK. Base URL `https://api.groq.com/openai/v1`. Default model `openai/gpt-oss-120b`.
- **UI:** Streamlit.
- **Charts:** matplotlib (a static PNG for README and UI).

`requirements.txt` (exact):
```
hindsight-client>=0.10.0
openai>=1.40.0
httpx>=0.27.0
python-dotenv>=1.0.0
streamlit>=1.37.0
pandas>=2.0.0
matplotlib>=3.8.0
pytest>=8.0.0
```

Install: `python -m pip install -r requirements.txt` (with the venv activated: `venv\Scripts\activate`).

---

## 3. Repository layout (create exactly this)

```
hindsight-agent/
├─ .env                      # NOT committed (already ignored by the Python .gitignore — verify)
├─ .env.example
├─ .gitignore                # append: data/state/  data/cache/
├─ requirements.txt
├─ README.md
├─ app.py                    # Streamlit UI
├─ memsre/
│  ├─ __init__.py
│  ├─ config.py              # env + constants + paths
│  ├─ llm.py                 # Groq JSON client: cache, rate limiter, retries, JSON repair
│  ├─ hs.py                  # Hindsight client + REST helpers
│  ├─ store.py               # local JSON state: aliases, incidents, answer log, tag names
│  ├─ catalog.py             # load catalog/customers/questions; render catalog text
│  ├─ grading.py             # normalize() + grade()
│  ├─ agent.py               # the support agent (the "patient")
│  ├─ diagnose.py            # incident creation + diagnosis + classify()
│  ├─ repair.py              # apply_fix / undo_fix / reask
│  └─ lessons.py             # SRE lessons bank + proactive identity scan (Tier 3)
├─ scripts/
│  ├─ smoke.py
│  ├─ seed.py
│  └─ eval.py
├─ tests/
│  ├─ test_grading.py
│  └─ test_classify.py
├─ data/
│  ├─ seed/
│  │  ├─ catalog.json
│  │  ├─ customers.json
│  │  ├─ events.jsonl
│  │  └─ questions.json
│  ├─ state/                 # gitignored, created at runtime
│  ├─ cache/                 # gitignored, created at runtime
│  └─ results/               # committed (eval_latest.json)
└─ docs/
   └─ before_after.png       # generated by eval.py, committed
```

**Step 0 hygiene:** if a file `smoke_test.py` exists at the repo root and contains a raw API key, **delete it**. Make sure `.env` is listed in `.gitignore`.

---

## 4. Configuration

`.env.example` (commit this; the real `.env` has the same keys with real values):
```
HINDSIGHT_BASE_URL=https://api.hindsight.vectorize.io
HINDSIGHT_API_KEY=
GROQ_API_KEY=
# Optional: several Groq keys, comma-separated, used round-robin (raises throughput)
GROQ_API_KEYS=
GROQ_MODEL=openai/gpt-oss-120b
MAIN_BANK_ID=memsre-lumora-support
LESSONS_BANK_ID=memsre-lessons
GROQ_TPM_BUDGET=7000
```

`memsre/config.py`:
- Load `.env` with `python-dotenv`.
- Expose these constants:
  - `HINDSIGHT_BASE_URL`, `HINDSIGHT_API_KEY`, `GROQ_KEYS` (a list: from `GROQ_API_KEYS` if set, else `[GROQ_API_KEY]`), `GROQ_MODEL`, `MAIN_BANK_ID`, `LESSONS_BANK_ID`, `GROQ_TPM_BUDGET` (int).
  - Paths: `ROOT`, `SEED_DIR=data/seed`, `STATE_DIR=data/state`, `CACHE_DIR=data/cache`, `RESULTS_DIR=data/results`, `DOCS_DIR=docs`. Create the directories on import.
- `check()` raises a clear error if `HINDSIGHT_API_KEY` or every Groq key is missing. **Never print keys.**

---

## 5. Hindsight API — verified reference (use exactly these)

Python client (sync helpers):
```python
from hindsight_client import Hindsight
hs = Hindsight(base_url=HINDSIGHT_BASE_URL, api_key=HINDSIGHT_API_KEY, timeout=120.0)

hs.get_version()                                         # smoke test
hs.create_bank(bank_id=..., name=..., retain_mission=...) # create bank
hs.retain(bank_id, content=str, timestamp=datetime, context=str,
          document_id=str, metadata={str: str}, tags=[str])    # synchronous extraction
resp = hs.recall(bank_id, query=str, types=["world", "experience"],
                 max_tokens=2048, budget="mid",
                 tags=[...], tags_match="any_strict")
for r in resp.results:   # fields: id, text, type, tags, metadata, occurred_start,
    ...                  #         mentioned_at, document_id, source_fact_ids
```

**Tag filter semantics (verified):** `tags_match="any_strict"` returns only memories carrying at least one of the given tags, and excludes untagged ones. **Always use `any_strict` for customer-scoped recall.** Omit `tags` entirely to search the whole bank.

REST helpers (use `httpx`, header `Authorization: Bearer <HINDSIGHT_API_KEY>`, base `f"{HINDSIGHT_BASE_URL}/v1/default/banks/{bank_id}"`):

| Purpose | Method + path | Body / params | Notes |
|---|---|---|---|
| Delete bank | `DELETE /v1/default/banks/{bank}` | – | Ignore 404 |
| Invalidate memory (quarantine) | `PATCH …/memories/{memory_id}` | `{"state": "invalidated", "reason": "<text>"}` | Reversible. Hindsight re-computes derived observations |
| Restore memory (undo) | `PATCH …/memories/{memory_id}` | `{"state": "valid"}` | |
| Delete a document (undo a retained doc) | `DELETE …/documents/{document_id}` | – | Removes its memories. Ignore 404 |
| List memories | `GET …/memories/list` | params `type`, `q`, `state`, `limit`, `offset` | Response has `items` (each item has `proof_count`, `tags`, `state`, `fact_type`, `source_memory_ids`) |
| List tags | `GET …/tags` | params `q` (e.g. `customer:*`) | Response `items: [{tag, count}]` |
| List operations | `GET …/operations` | params `status` (`pending` / `processing`), `limit=1` | Response `operations: [...]` |

`memsre/hs.py` must expose:
```python
def client() -> Hindsight                     # singleton
def reset_bank(bank_id: str, name: str, retain_mission: str) -> None   # delete (ignore 404) then create
def retain_event(bank_id, content, date_iso, context, document_id, tags, metadata) -> None
def recall(bank_id, query, tags=None, types=("world","experience"), max_tokens=2048) -> list[Mem]
def invalidate(bank_id, memory_id, reason) -> None
def restore(bank_id, memory_id) -> None
def delete_document(bank_id, document_id) -> None
def list_memories(bank_id, type=None, q=None, state=None, limit=100) -> list[dict]
def list_tags(bank_id, q) -> list[str]
def wait_for_idle(bank_id, timeout_s=60) -> bool   # poll operations(pending/processing) every 1s; True if idle
```

`Mem` is a dataclass (define it in `hs.py`), converted from `RecallResult`:
```python
@dataclass
class Mem:
    id: str
    text: str
    date: str          # YYYY-MM-DD from occurred_start, else mentioned_at, else ""
    tags: list[str]
    source: str        # metadata["source"] if present, else tag "source:*" value, else ""
    document_id: str | None
```

The date parameter in `retain_event` is an ISO date `YYYY-MM-DD`. Convert it to `datetime(y, m, d, 10, 0, tzinfo=timezone.utc)`. `metadata` values must be strings.

On any network error, retry once after 3 s, then raise.

---

## 6. LLM usage rules (`memsre/llm.py`)

One public function:
```python
def llm_json(system: str, user: str, *, max_completion_tokens: int = 1200) -> dict
```

Behavior:
1. **Client:** `OpenAI(base_url="https://api.groq.com/openai/v1", api_key=<key>)`. Pick keys round-robin from `GROQ_KEYS`.
2. **Call:** `client.chat.completions.create(model=GROQ_MODEL, messages=[system, user], temperature=0, response_format={"type": "json_object"}, max_completion_tokens=..., extra_body={"reasoning_effort": "low"})`.
   - If the API returns 400 mentioning `reasoning_effort`, `response_format` or `max_completion_tokens`, retry without that parameter (use `max_tokens` instead of `max_completion_tokens`). Remember this for the rest of the process.
3. **Disk cache:** key = sha256 of `json.dumps([GROQ_MODEL, system, user, max_completion_tokens])`. Cache file `data/cache/llm_cache.json`. On a cache hit, return without calling the API. Write the file after every new result.
4. **Rate limiter (per key):**
   - Estimated tokens = `(len(system) + len(user)) // 4 + 500`.
   - Keep a deque of `(time, tokens)` for the last 60 s. If `sum + estimate > GROQ_TPM_BUDGET`, sleep until enough entries expire.
   - Also enforce a minimum of 2.1 s between calls on the same key.
5. **Retries:** on 429, 5xx or timeout, sleep `Retry-After` (if present) or `5 * 2**attempt` seconds, up to 5 attempts.
6. **JSON parsing:** `json.loads(content)`.
   - On failure, extract the first `{...}` block with a regex and try again.
   - Still failing: re-ask once with the user message plus `"\n\nYour previous reply was not valid JSON. Return ONLY the JSON object."`
   - Then raise `LLMError`.
7. Log to stdout one line per call: `[llm] cache|api  <first 60 chars of user>  <elapsed>s`.

---

## 7. Seed data — write these files verbatim

### 7.1 `data/seed/catalog.json`
```json
{
  "vendor": "Lumora Cloud",
  "plans": {
    "starter":    {"display": "Starter",    "sso": false, "audit_log_export": false, "api_rate_limit_per_min": 100,   "data_retention_days": 30,  "support_sla": "48h", "dedicated_csm": false},
    "growth":     {"display": "Growth",     "sso": false, "audit_log_export": false, "api_rate_limit_per_min": 1000,  "data_retention_days": 180, "support_sla": "24h", "dedicated_csm": false},
    "enterprise": {"display": "Enterprise", "sso": true,  "audit_log_export": true,  "api_rate_limit_per_min": 10000, "data_retention_days": 730, "support_sla": "4h",  "dedicated_csm": true}
  },
  "regions": {"ap-south-1": "Mumbai", "ap-south-2": "Hyderabad", "eu-west-1": "Ireland", "us-east-1": "N. Virginia"}
}
```

### 7.2 `data/seed/customers.json`
The support team's customer list (CRM names). Billing-only names are deliberately absent.
```json
[
  {"key": "kestrel",   "name": "Kestrel Logistics"},
  {"key": "saffron",   "name": "Saffron Retail"},
  {"key": "pinecrest", "name": "Pinecrest Hospitals"},
  {"key": "quartz",    "name": "Quartz Mobility"},
  {"key": "vanadium",  "name": "Vanadium Energy"},
  {"key": "tidewater", "name": "Tidewater Foods"}
]
```

### 7.3 `data/seed/events.jsonl`
One JSON object per line.
- `customer_key` is the key **as that source system knows the customer**. Billing uses its own keys (`anvaya`, `mehta-bros`). **This is the planted defect.**
- Retain each event with:
  - tags: `customer:<customer_key>`, `source:<source>`
  - metadata: `source`, `event_id`, `customer_name`
  - `document_id` = `id`
  - context = `"<source> record for <customer_name>"`
```jsonl
{"id":"evt-k1","date":"2026-04-22","source":"crm_notes","customer_key":"kestrel","customer_name":"Kestrel Logistics","content":"Discovery call with Kestrel Logistics (Arjun Rao, VP Operations). Kestrel runs 1,200 trucks across South India and wants fleet analytics dashboards."}
{"id":"evt-k2","date":"2026-06-03","source":"crm_notes","customer_key":"kestrel","customer_name":"Kestrel Logistics","content":"Kestrel Logistics signed a 12-month Lumora Cloud Enterprise plan starting 1 June 2026. Arjun Rao said SSO with Azure AD and audit log exports are must-haves for their SOC 2 audit."}
{"id":"evt-k3","date":"2026-06-05","source":"onboarding_form","customer_key":"kestrel","customer_name":"Kestrel Logistics","content":"Kestrel Logistics workspace provisioned in AWS region ap-south-1 (Mumbai). Workspace admin: Ravi Kumar, ravi.k@anvaya.in."}
{"id":"evt-k4","date":"2026-06-20","source":"support_ticket","customer_key":"kestrel","customer_name":"Kestrel Logistics","content":"Ticket #4112 from ravi.k@anvaya.in (Kestrel Logistics): asked where to download the June invoice. Resolved by sharing the billing portal link."}
{"id":"evt-k5","date":"2026-07-11","source":"csm_notes","customer_key":"kestrel","customer_name":"Kestrel Logistics","content":"Kestrel Logistics asked for a custom fuel-efficiency dashboard. Logged as feature request FR-219."}
{"id":"evt-a1","date":"2026-08-14","source":"billing_system","customer_key":"anvaya","customer_name":"Anvaya Technologies Pvt Ltd","content":"Billing event: account Anvaya Technologies Pvt Ltd (billing contact accounts@anvaya.in) changed plan from Enterprise to Growth, effective 1 August 2026. Reason recorded: budget cuts."}
{"id":"evt-a2","date":"2026-08-29","source":"billing_system","customer_key":"anvaya","customer_name":"Anvaya Technologies Pvt Ltd","content":"Billing event: Anvaya Technologies Pvt Ltd paid invoice INV-20260801 for the Growth plan (Rs 1,85,000 including GST)."}
{"id":"evt-s1","date":"2026-05-10","source":"crm_notes","customer_key":"saffron","customer_name":"Saffron Retail","content":"Saffron Retail (Neha Kapoor, Head of IT) is on the Lumora Growth plan. They run 85 stores across Maharashtra and Gujarat."}
{"id":"evt-s2","date":"2026-05-12","source":"onboarding_form","customer_key":"saffron","customer_name":"Saffron Retail","content":"Saffron Retail workspace hosted in AWS region ap-south-1 (Mumbai). Workspace admin contact: it-desk@mehtabros.co.in."}
{"id":"evt-s3","date":"2026-06-25","source":"csm_notes","customer_key":"saffron","customer_name":"Saffron Retail","content":"Saffron Retail wants weekly inventory reports emailed to their store managers."}
{"id":"evt-s4","date":"2026-07-02","source":"support_ticket","customer_key":"saffron","customer_name":"Saffron Retail","content":"Ticket #4388 from it-desk@mehtabros.co.in (Saffron Retail): asked whether SSO can be enabled. Told that SSO requires the Enterprise plan."}
{"id":"evt-m1","date":"2026-09-01","source":"billing_system","customer_key":"mehta-bros","customer_name":"Mehta Brothers Trading LLP","content":"Billing event: Mehta Brothers Trading LLP (billing contact accounts@mehtabros.co.in) upgraded from the Growth plan to the Enterprise plan, effective 1 September 2026."}
{"id":"evt-m2","date":"2026-09-03","source":"billing_system","customer_key":"mehta-bros","customer_name":"Mehta Brothers Trading LLP","content":"Billing event: Mehta Brothers Trading LLP paid invoice INV-20260901 for the Enterprise plan (Rs 6,40,000 including GST)."}
{"id":"evt-p1","date":"2026-04-15","source":"onboarding_form","customer_key":"pinecrest","customer_name":"Pinecrest Hospitals","content":"Pinecrest Hospitals signed the Lumora Enterprise plan. Their workspace is hosted in AWS region ap-south-1 (Mumbai). Admin: Dr. Kavita Menon, kavita.menon@pinecresthospitals.in."}
{"id":"evt-p2","date":"2026-06-18","source":"csm_notes","customer_key":"pinecrest","customer_name":"Pinecrest Hospitals","content":"Pinecrest Hospitals asked about moving their workspace to Hyderabad to meet state data residency rules. Planned for September."}
{"id":"evt-p3","date":"2026-09-10","source":"support_ticket","customer_key":"pinecrest","customer_name":"Pinecrest Hospitals","content":"Ticket #4671 (Pinecrest Hospitals): workspace migration completed on 8 September 2026. Pinecrest's workspace now runs in AWS region ap-south-2 (Hyderabad); ap-south-1 is decommissioned for them."}
{"id":"evt-p4","date":"2026-09-12","source":"csm_notes","customer_key":"pinecrest","customer_name":"Pinecrest Hospitals","content":"Pinecrest Hospitals confirmed dashboards work after the migration. Their CSM is Farah Siddiqui."}
{"id":"evt-q1","date":"2026-05-20","source":"crm_notes","customer_key":"quartz","customer_name":"Quartz Mobility","content":"Quartz Mobility (EV scooter rentals, Bengaluru) signed the Lumora Starter plan. Contact: Vikram Shetty, vikram@quartzmobility.in."}
{"id":"evt-q2","date":"2026-05-21","source":"onboarding_form","customer_key":"quartz","customer_name":"Quartz Mobility","content":"Quartz Mobility workspace hosted in AWS region ap-south-1 (Mumbai)."}
{"id":"evt-q3","date":"2026-08-07","source":"support_ticket","customer_key":"quartz","customer_name":"Quartz Mobility","content":"Ticket #4520 from vikram@quartzmobility.in (Quartz Mobility): hit the API rate limit during a data backfill; advised to batch requests."}
{"id":"evt-v1","date":"2026-03-30","source":"crm_notes","customer_key":"vanadium","customer_name":"Vanadium Energy","content":"Vanadium Energy (solar plants, Rajasthan) renewed the Lumora Enterprise plan for 24 months from 1 April 2026."}
{"id":"evt-v2","date":"2026-04-02","source":"onboarding_form","customer_key":"vanadium","customer_name":"Vanadium Energy","content":"Vanadium Energy workspace hosted in AWS region eu-west-1 (Ireland) because their parent company is in Europe. Admin: Sofia Brandt, sofia.brandt@vanadium-energy.eu."}
{"id":"evt-v3","date":"2026-07-15","source":"csm_notes","customer_key":"vanadium","customer_name":"Vanadium Energy","content":"Vanadium Energy's dedicated CSM is Farah Siddiqui. Quarterly business review scheduled for October."}
{"id":"evt-t1","date":"2026-02-11","source":"crm_notes","customer_key":"tidewater","customer_name":"Tidewater Foods","content":"Tidewater Foods (seafood exporter, Kochi) is on the Lumora Growth plan."}
{"id":"evt-t2","date":"2026-02-12","source":"onboarding_form","customer_key":"tidewater","customer_name":"Tidewater Foods","content":"Tidewater Foods workspace hosted in AWS region ap-south-1 (Mumbai). Contact: Anil Varghese, anil@tidewaterfoods.in."}
{"id":"evt-t3","date":"2026-07-25","source":"support_ticket","customer_key":"tidewater","customer_name":"Tidewater Foods","content":"Ticket #4499 (Tidewater Foods): asked how long their data is retained; told the Growth plan retains data for 180 days."}
```

**Ground truth (for your understanding; the eval uses `questions.json`):**

| Customer | Current plan | Region | Billing name |
|---|---|---|---|
| Kestrel | Growth (downgraded 1 Aug) | ap-south-1 | Anvaya Technologies Pvt Ltd |
| Saffron | Enterprise (upgraded 1 Sep) | ap-south-1 | Mehta Brothers Trading LLP |
| Pinecrest | Enterprise | ap-south-2 (moved 8 Sep) | — |
| Quartz | Starter | ap-south-1 | — |
| Vanadium | Enterprise | eu-west-1 | — |
| Tidewater | Growth | ap-south-1 | — |

### 7.4 `data/seed/questions.json`
`format` is passed to the agent. `accepted` is compared after `normalize()` (§8). `defect` is a label for reporting only.
```json
[
  {"id":"Q01","customer":"kestrel","question":"Can Kestrel Logistics export audit logs?","format":"yes or no","accepted":["no"],"defect":"resolution","correction":"Wrong. The customer says audit log export fails. They moved to the Growth plan on 1 August 2026, so audit log export is not included."},
  {"id":"Q02","customer":"kestrel","question":"Which Lumora plan is Kestrel Logistics on right now?","format":"one of: starter, growth, enterprise","accepted":["growth"],"defect":"resolution","correction":"Wrong. Kestrel Logistics has been on the Growth plan since 1 August 2026."},
  {"id":"Q03","customer":"kestrel","question":"What is Kestrel Logistics' API rate limit?","format":"integer, requests per minute","accepted":["1000"],"defect":"resolution","correction":"Wrong. Kestrel is on the Growth plan now, so the limit is 1000 requests per minute."},
  {"id":"Q04","customer":"kestrel","question":"Does Kestrel Logistics have a dedicated customer success manager?","format":"yes or no","accepted":["no"],"defect":"resolution","correction":"Wrong. Kestrel is on the Growth plan now; a dedicated CSM is Enterprise-only."},
  {"id":"Q05","customer":"saffron","question":"Can Saffron Retail enable SSO?","format":"yes or no","accepted":["yes"],"defect":"resolution","correction":"Wrong. Saffron Retail upgraded to the Enterprise plan on 1 September 2026, so SSO is included."},
  {"id":"Q06","customer":"saffron","question":"Which Lumora plan is Saffron Retail on right now?","format":"one of: starter, growth, enterprise","accepted":["enterprise"],"defect":"resolution","correction":"Wrong. Saffron Retail upgraded to Enterprise on 1 September 2026."},
  {"id":"Q07","customer":"saffron","question":"How long is Saffron Retail's data retained?","format":"integer, days","accepted":["730"],"defect":"resolution","correction":"Wrong. Saffron is on Enterprise now, so data is retained for 730 days."},
  {"id":"Q08","customer":"saffron","question":"What support response SLA does Saffron Retail get?","format":"hours, like 4h","accepted":["4h"],"defect":"resolution","correction":"Wrong. Saffron is on Enterprise now, so the support SLA is 4h."},
  {"id":"Q09","customer":"pinecrest","question":"Which AWS region hosts Pinecrest Hospitals' workspace?","format":"AWS region code, like ap-south-1","accepted":["ap-south-2"],"defect":"freshness_candidate","correction":"Wrong. Pinecrest migrated to ap-south-2 (Hyderabad) on 8 September 2026."},
  {"id":"Q10","customer":"pinecrest","question":"Is Pinecrest Hospitals' workspace still hosted in Mumbai?","format":"yes or no","accepted":["no"],"defect":"freshness_candidate","correction":"Wrong. Pinecrest moved to Hyderabad (ap-south-2) on 8 September 2026."},
  {"id":"Q11","customer":"pinecrest","question":"Can Pinecrest Hospitals export audit logs?","format":"yes or no","accepted":["yes"],"defect":"none","correction":"Wrong. Pinecrest is on Enterprise, which includes audit log export."},
  {"id":"Q12","customer":"quartz","question":"Which Lumora plan is Quartz Mobility on?","format":"one of: starter, growth, enterprise","accepted":["starter"],"defect":"none","correction":"Wrong. Quartz Mobility is on the Starter plan."},
  {"id":"Q13","customer":"quartz","question":"What is Quartz Mobility's API rate limit?","format":"integer, requests per minute","accepted":["100"],"defect":"none","correction":"Wrong. Quartz is on Starter: 100 requests per minute."},
  {"id":"Q14","customer":"quartz","question":"Can Quartz Mobility use SSO?","format":"yes or no","accepted":["no"],"defect":"none","correction":"Wrong. Quartz is on Starter, which has no SSO."},
  {"id":"Q15","customer":"vanadium","question":"Which AWS region hosts Vanadium Energy's workspace?","format":"AWS region code, like ap-south-1","accepted":["eu-west-1"],"defect":"none","correction":"Wrong. Vanadium Energy is hosted in eu-west-1."},
  {"id":"Q16","customer":"vanadium","question":"Does Vanadium Energy have a dedicated customer success manager?","format":"yes or no","accepted":["yes"],"defect":"none","correction":"Wrong. Vanadium is on Enterprise and has a dedicated CSM, Farah Siddiqui."},
  {"id":"Q17","customer":"vanadium","question":"How long is Vanadium Energy's data retained?","format":"integer, days","accepted":["730"],"defect":"none","correction":"Wrong. Vanadium is on Enterprise: 730 days."},
  {"id":"Q18","customer":"tidewater","question":"Which Lumora plan is Tidewater Foods on?","format":"one of: starter, growth, enterprise","accepted":["growth"],"defect":"none","correction":"Wrong. Tidewater Foods is on the Growth plan."},
  {"id":"Q19","customer":"tidewater","question":"Can Tidewater Foods export audit logs?","format":"yes or no","accepted":["no"],"defect":"none","correction":"Wrong. Tidewater is on Growth, which has no audit log export."},
  {"id":"Q20","customer":"tidewater","question":"What support response SLA does Tidewater Foods get?","format":"hours, like 4h","accepted":["24h"],"defect":"none","correction":"Wrong. Tidewater is on Growth: 24h support SLA."}
]
```

---

## 8. Small modules

### 8.1 `memsre/catalog.py`
- `load_catalog() -> dict`, `load_customers() -> list[dict]`, `load_questions() -> list[dict]`, `load_events() -> list[dict]`.
- `customer_name(key) -> str` looks up `customers.json`, then `data/state/tag_names.json`, then falls back to `key`.
- `catalog_text() -> str` renders exactly this form (one line per plan):
```
Starter: SSO no; audit log export no; API rate limit 100 requests/min; data retention 30 days; support SLA 48h; dedicated CSM no.
Growth: SSO no; audit log export no; API rate limit 1000 requests/min; data retention 180 days; support SLA 24h; dedicated CSM no.
Enterprise: SSO yes; audit log export yes; API rate limit 10000 requests/min; data retention 730 days; support SLA 4h; dedicated CSM yes.
Regions: ap-south-1 = Mumbai, ap-south-2 = Hyderabad, eu-west-1 = Ireland, us-east-1 = N. Virginia.
```

### 8.2 `memsre/grading.py`
```python
def normalize(s: str) -> str:
    # lowercase, strip, drop trailing '.', remove ',' and collapse whitespace
    # "<n> h|hr|hrs|hour|hours"                    -> "<n>h"
    # "<n> day|days"                               -> "<n>"
    # "<n> requests/min|requests per minute|req/min|rpm" -> "<n>"
    # startswith "yes" -> "yes"; startswith "no " or == "no" -> "no"
def grade(short_answer: str, accepted: list[str]) -> bool:
    return normalize(short_answer) in {normalize(a) for a in accepted}   # EXACT match, never substring
```
**Exact match is required:** "10000" must not count as "1000".

### 8.3 `memsre/store.py` (local JSON state in `data/state/`)
- `aliases.json`: `{"kestrel": ["anvaya"]}` (keys **without** the `customer:` prefix, symmetric links stored on both keys).
  - `get_alias_keys(key) -> list[str]`, `link(a, b)`, `unlink(a, b)`.
  - `customer_tags(key) -> list[str]` returns `["customer:<key>"] + ["customer:<alias>" ...]`.
- `incidents.json`: a list of incident dicts (§9.3).
  - `add_incident(inc)`, `update_incident(inc)`, `list_incidents()` (newest first), `get_incident(id)`, `next_incident_id()` (returns `"INC-001"`, `"INC-002"`, …).
- `answers.jsonl`: `log_answer(record) -> answer_id` (`"ANS-0001"`, …) and `answers_using(memory_ids, exclude_runs=("eval-after",)) -> list[dict]`.
- `tag_names.json`: `{"customer:anvaya": "Anvaya Technologies Pvt Ltd", ...}`, written by `seed.py`.
- `reset_state()` empties all four files.
- All writes are atomic: write to `.tmp`, then `os.replace`.

---

## 9. Core modules

### 9.1 `memsre/agent.py` — the support agent (the "patient")

```python
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

def answer(customer_key: str, question: str, answer_format: str | None = None, run: str = "live") -> AgentAnswer
```

Steps:
1. `tags = store.customer_tags(customer_key)`, `name = catalog.customer_name(customer_key)`.
2. `mems = hs.recall(MAIN_BANK_ID, query=f"{name}: {question}", tags=tags)` (uses `any_strict`, types `world` and `experience`). Keep the first **12**.
3. Memory lines, one per memory: `[<id>] (<date>) [<source>] <text>`.
4. Call `llm_json(AGENT_SYSTEM, AGENT_USER)` using the prompts in §10.1.
5. Drop any `used_memory_ids` that were not shown (hallucinated ids). If `short_answer` is missing, set it to `""`.
6. `store.log_answer({...})`, then return an `AgentAnswer`.
7. CLI: `python -m memsre.agent kestrel "Can Kestrel Logistics export audit logs?"` prints the answer, the short answer and the used memories.

### 9.2 `memsre/diagnose.py` — incident + diagnosis

```python
def create_incident(ans: AgentAnswer, correction: str, answer_format: str | None = None) -> dict
```

Steps (in order). Store every intermediate result in the incident.

1. **Culprit.** Call `llm_json` with the culprit prompt (§10.2) over `ans.used_memories`.
   - Result: `culprit_ids`, `wrong_claim`, `culprit_asserts_current_state`, `reason`.
   - Keep only ids that are in `used_memory_ids`.
2. **Evidence search.** `cands = hs.recall(MAIN_BANK_ID, query=correction, tags=None, max_tokens=2048)` — the **whole bank, no tag filter**.
   - Remove culprits and keep the first 15.
   - Call `llm_json` with the evidence prompt (§10.3). Result: `supporting_ids`.
   - Keep only ids present in `cands`.
3. **Identity check** (only if some supporting memory has no `customer:*` tag in `store.customer_tags(customer_key)`):
   - Take the first foreign `customer:*` tag, `foreign_key` = the tag without its prefix.
   - `facts_a = hs.recall(MAIN, "contact email admin billing plan", tags=store.customer_tags(customer_key), max_tokens=1000)[:8]`
   - `facts_b = hs.recall(MAIN, "contact email admin billing plan", tags=[foreign tag], max_tokens=1000)[:8]`
   - Call `llm_json` with the identity prompt (§10.4). Result: `same_customer`, `confidence`, `linking_evidence`, `reason`.
   - `identity_confirmed = same_customer and confidence >= 0.7`.
4. **Classify:** `failure_type = classify(culprits, supporting, used_ids, customer_tags, identity_confirmed)` (§9.4).
5. **Blast radius:** `store.answers_using(culprit_ids)` gives the count and answer ids.
6. **Root cause text** from the templates in §9.5, and **recommended_fix** actions (human-readable strings) from §9.6.
7. `status = "open"` (or `"no_fix"` for EXECUTION/UNKNOWN). Save with `store.add_incident` and return it.

CLI: `python -m memsre.diagnose` runs `agent.answer("kestrel", "Can Kestrel Logistics export audit logs?")`, then `create_incident` with Q01's correction, and pretty-prints the incident.

### 9.3 Incident schema (exact keys)
```json
{
  "id": "INC-001", "created_at": "<iso>", "status": "open|fixed|reverted|no_fix|prevented",
  "customer_key": "kestrel", "customer_name": "Kestrel Logistics",
  "question": "...", "answer_format": null, "wrong_answer": "...", "wrong_short_answer": "...",
  "correction": "...",
  "used_memories": [{"id": "...", "text": "...", "date": "...", "tags": ["..."], "source": "..."}],
  "culprits": [ same shape ], "wrong_claim": "...", "culprit_asserts_current_state": true,
  "supporting": [ same shape ],
  "identity": {"foreign_tag": "customer:anvaya", "foreign_name": "Anvaya Technologies Pvt Ltd",
               "same_customer": true, "confidence": 0.92, "linking_evidence": "...", "reason": "..."},
  "failure_type": "RESOLUTION",
  "root_cause": "...",
  "blast_radius": {"answers_affected": 3, "answer_ids": ["ANS-0001"]},
  "recommended_fix": ["Link 'Kestrel Logistics' with 'Anvaya Technologies Pvt Ltd' as the same customer", "..."],
  "applied_actions": [],
  "reask": null
}
```
`identity` is `null` when no identity check ran.

### 9.4 `classify()` — pure function, unit-tested

```python
FAILURE_TYPES = ["RESOLUTION", "FRESHNESS", "RECALL_MISS", "EXECUTION", "MISSING_KNOWLEDGE", "UNKNOWN"]

def classify(culprits: list[Mem], supporting: list[Mem], used_ids: list[str],
             customer_tags: list[str], identity_confirmed: bool | None) -> str:
    cust = set(customer_tags)
    def ctags(m): return {t for t in m.tags if t.startswith("customer:")}
    if not supporting:
        return "MISSING_KNOWLEDGE" if culprits else "UNKNOWN"
    foreign = [m for m in supporting if not (ctags(m) & cust)]
    local   = [m for m in supporting if (ctags(m) & cust)]
    if foreign and identity_confirmed:
        return "RESOLUTION"
    if not local:
        return "UNKNOWN"
    if any(m.id in used_ids for m in local):
        return "EXECUTION"
    newest_culprit = max((m.date for m in culprits if m.date), default="")
    if culprits and any(m.date and m.date > newest_culprit for m in local):
        return "FRESHNESS"
    return "RECALL_MISS"
```

### 9.5 Root-cause templates (UI copy, verbatim)

| Type | Text |
|---|---|
| RESOLUTION | `The correct fact was stored under a different name for the same customer ('{foreign_name}'). The two records were never linked, so the agent's recall for '{customer_name}' could not see it. Linking evidence: {linking_evidence}.` |
| FRESHNESS | `A newer fact superseded the memory the agent used, but the outdated memory was recalled and the newer one was not.` |
| RECALL_MISS | `The correct fact exists under this customer but was not retrieved for this question.` |
| EXECUTION | `The correct memory was retrieved, but the agent still answered wrong. This is a model or prompt problem — memory is not at fault.` |
| MISSING_KNOWLEDGE | `Memory never contained the correct fact.` |
| UNKNOWN | `No memory-level cause could be confirmed.` |

### 9.6 `memsre/repair.py` — apply / undo / re-ask

```python
def apply_fix(incident_id: str) -> dict        # returns the updated incident
def undo_fix(incident_id: str) -> dict
def reask(incident_id: str) -> dict            # sets incident["reask"]
def link_identities(key_a, key_b, evidence, incident_id) -> list[dict]   # reused by the proactive scan
```

`apply_fix` actions by `failure_type`. Record every action in `applied_actions` so undo can reverse it.

- **RESOLUTION:**
  - `link_identities(customer_key, foreign_key, linking_evidence, incident_id)`:
    - `store.link(a, b)` → action `{"kind": "alias", "a": a, "b": b}`.
    - `hs.retain_event(MAIN, content=f"Identity link verified by Memory SRE ({incident_id}): '{name_a}' and '{name_b}' are the same customer. Evidence: {evidence}.", date_iso=today, context="Memory SRE identity link", document_id=f"sre-alias-{a}-{b}", tags=[f"customer:{a}", f"customer:{b}", "sre:alias-link"], metadata={"source": "memory_sre"})` → action `{"kind": "retain_doc", "bank": MAIN, "document_id": ...}`.
  - Then, if `culprit_asserts_current_state`: for each culprit, `hs.invalidate(MAIN, id, reason=f"Memory SRE {incident_id}: superseded by newer evidence under linked identity")` → action `{"kind": "invalidate", "bank": MAIN, "memory_id": id}`.
- **FRESHNESS:** invalidate each culprit (same reason text, but "superseded by newer evidence").
- **RECALL_MISS:** retain a pinned restatement for the customer:
  - `content=f"{customer_name}: {supporting[0].text}"`
  - `document_id=f"sre-pin-{incident_id}"`
  - `tags=[f"customer:{customer_key}", "sre:pin"]`
  - Record it as a `retain_doc` action.
- **MISSING_KNOWLEDGE:** retain the correction:
  - `content=f"Verified correction for {customer_name}: {correction}"`
  - `document_id=f"sre-correction-{incident_id}"`
  - `tags=[f"customer:{customer_key}", "sre:correction"]`
  - Then invalidate culprits if `culprit_asserts_current_state`.
- **EXECUTION / UNKNOWN:** raise `ValueError("No automatic memory fix for this failure type")`. The UI disables the button.

After the actions: `hs.wait_for_idle(MAIN, 30)`, then `lessons.record(incident)` (only if Tier 3 is implemented; guard with try/except), then set `status = "fixed"` and save.

`undo_fix` reverses `applied_actions` in reverse order:
- `invalidate` → `hs.restore`
- `alias` → `store.unlink`
- `retain_doc` → `hs.delete_document`

Then clear `applied_actions`, set `status="reverted"` and `reask=None`, and save.

`reask`: call `agent.answer(customer_key, question, answer_format, run="reask")` and store `{"answer", "short_answer", "used_memory_ids", "used_memories"}` in `incident["reask"]`.

---

## 10. Prompts (verbatim)

### 10.1 Agent

`AGENT_SYSTEM`:
```
You are the support assistant for Lumora Cloud, a SaaS analytics platform. You answer a support rep's question about ONE customer.

You have two sources:
1. PRODUCT CATALOG — authoritative for what each plan includes.
2. CUSTOMER MEMORIES — what we know about this customer. Each memory has an ID, a date and a source.

Rules:
- Base every customer-specific fact ONLY on CUSTOMER MEMORIES. Never invent facts.
- If memories conflict, trust the most recent one.
- If the memories do not contain the answer, say you don't know.
- In used_memory_ids list ONLY the IDs of memories you relied on.

Return ONLY a JSON object:
{"answer": "<1-2 sentence answer for the support rep>", "short_answer": "<the answer in the requested SHORT ANSWER FORMAT>", "used_memory_ids": ["<id>", "..."]}
```

`AGENT_USER`:
```
PRODUCT CATALOG:
{catalog_text}

CUSTOMER: {customer_name}
CUSTOMER MEMORIES:
{memory_lines}

QUESTION: {question}
SHORT ANSWER FORMAT: {answer_format or "a brief value"}
```

### 10.2 Culprit

`SRE_SYSTEM` (shared by §10.2–§10.4):
```
You are Memory SRE, a reliability engineer for AI agent memory. You diagnose why an AI agent gave a wrong answer. Be precise and conservative. Return ONLY a JSON object.
```

Culprit user prompt:
```
The support agent answered a question wrongly.

QUESTION: {question}
AGENT'S ANSWER: {wrong_answer}
CORRECTION FROM THE SUPPORT REP: {correction}

MEMORIES THE AGENT USED:
{used_memory_lines}

Which of these memories support the WRONG answer? A memory supports the wrong answer if the agent's wrong claim follows from it.
Return JSON: {"culprit_ids": ["<id>", "..."], "wrong_claim": "<the wrong claim in one sentence>", "culprit_asserts_current_state": <true if a culprit states a current state that can change over time, such as a plan, region or status>, "reason": "<one sentence>"}
If no memory supports the wrong answer, return an empty culprit_ids list.
```

### 10.3 Evidence
```
CORRECTION FROM THE SUPPORT REP about the customer '{customer_name}': {correction}

CANDIDATE MEMORIES FROM THE WHOLE MEMORY BANK (they may name customers differently):
{candidate_lines}

Which candidate memories are evidence FOR the correction about this customer — even if they refer to the customer by a different name (for example a legal entity name, a billing account name or an email domain)? Do not select memories about clearly different companies unless something links them to this customer.
Return JSON: {"supporting_ids": ["<id>", "..."], "reason": "<one sentence>"}
```
Candidate line format: `[<id>] (<date>) [tags: <comma-separated customer:* tags>] <text>`.

### 10.4 Identity
```
Decide whether two customer records in our memory refer to the SAME real-world customer.

RECORD A — known to the support team as '{name_a}':
{facts_a}

RECORD B — appears in our records as '{name_b}':
{facts_b}

{lessons_block}
Look for concrete linking evidence: shared email domains, shared people, account numbers, or explicit statements. Do not decide from similar-sounding names alone.
Return JSON: {"same_customer": true or false, "confidence": <0.0-1.0>, "linking_evidence": "<exact quote(s) from the records>", "reason": "<one sentence>"}
```
`lessons_block` is `""` in diagnosis. In the proactive scan it is `LESSONS FROM PAST INCIDENTS:\n- <lesson 1>\n- <lesson 2>`.

---

## 11. `memsre/lessons.py` — Tier 3 (build only after the checkpoint in §14)

- `record(incident)`: `hs.retain_event(LESSONS_BANK_ID, …)` with:
  - `content=f"Incident {id} ({failure_type}) for '{customer_name}': {root_cause} Fix applied: {'; '.join(recommended_fix)}."`
  - `context="Memory SRE incident post-mortem"`
  - `document_id=f"lesson-{id}"`
  - `tags=["sre:lesson", f"type:{failure_type.lower()}"]`
  - `metadata={"source": "memory_sre"}`
- `learned(limit=10) -> list[dict]`: `hs.list_memories(LESSONS_BANK_ID, type="observation", limit=limit)`. Return `text` and `proof_count`. If that returns nothing (consolidation not finished yet), fall back to `hs.recall(LESSONS_BANK_ID, "What have we learned about memory failures?", types=("world", "experience", "observation"))`.
- `has_resolution_lesson() -> bool`: does any lesson text contain "RESOLUTION"? (Use `list_memories(LESSONS, q="RESOLUTION")`.)
- `proactive_identity_scan() -> list[dict]` (deterministic pre-filter, then the LLM confirms):
  1. `tags = hs.list_tags(MAIN_BANK_ID, q="customer:*")`.
  2. For each tag: `hs.recall(MAIN, "contact email admin billing", tags=[tag], max_tokens=800)`. Extract email domains with the regex `[\w.+-]+@([\w-]+(?:\.[\w-]+)+)`. Ignore `gmail.com`, `yahoo.com`, `outlook.com`, `hotmail.com`.
  3. Candidate pairs: tags sharing at least one domain that are **not already linked** in `store`.
  4. For each candidate: run the identity prompt with `lessons_block` built from `learned()` texts. Keep a pair if `same_customer and confidence >= 0.7`.
  5. Return proposals `[{"a": key, "b": key, "name_a", "name_b", "confidence", "linking_evidence", "shared_domain"}]`.
- `accept_proposal(p) -> dict`:
  - Create an incident with `failure_type="RESOLUTION"`, `status="prevented"`, `question=None`, `root_cause` from the template, and `blast_radius` 0.
  - Call `repair.link_identities(...)` and record the actions.
  - Call `record(incident)` and return the incident.

---

## 12. Streamlit app — `app.py`

- `st.set_page_config(page_title="Memory SRE", page_icon="🩺", layout="wide")`.
- Title: **"Memory SRE for Hindsight"**, caption: *"Find the memory that made your agent wrong — and fix it."*
- **Sidebar:**
  - bank ids;
  - counts: incidents, linked identities, answers logged;
  - the last eval `before% → after%`, if `data/results/eval_latest.json` exists;
  - a note: *"Reset: run `python scripts/seed.py` in a terminal."*

### Tab 1 — "Support Console"
- `selectbox` of customers (display names from `customers.json`).
- A row of 4 sample-question buttons for the selected customer (the first questions from `questions.json` for that customer). Clicking one fills the text input.
- `text_input` "Question" and an **Ask** button → `agent.answer(key, q)`. Store the result in `st.session_state["last_answer"]`.
- Show the answer in a bordered container, then **"Memories used"** as a table: short id (first 8 chars), date, source, text.
- Below the answer: "Was this correct?" with two buttons, **👍 Correct** (toast "Logged") and **👎 Wrong**.
  - 👎 reveals a `text_area` "What's actually true? (paste what the customer told you)" and a **Report & diagnose** button.
  - The button runs `create_incident` inside `st.spinner("Memory SRE is diagnosing…")`, then shows `st.success(f"{id} created — type {failure_type}. Open the Incidents tab.")` and sets `st.session_state["selected_incident"]`.

### Tab 2 — "Incidents"
- If there are no incidents: `st.info("No incidents yet.")`.
- `selectbox` of incidents, newest first, label `"{id} · {failure_type} · {customer_name} · {status}"`, defaulting to `selected_incident`.
- Incident view, top to bottom:
  1. **Header:** id, status, and a failure-type badge (colored markdown: RESOLUTION = orange, FRESHNESS = blue, RECALL_MISS = violet, EXECUTION = gray, MISSING_KNOWLEDGE = red).
  2. **What went wrong:** question, the agent's answer, and the correction.
  3. **Culprit memory:** each culprit's text, date, source and id, plus the "Wrong claim" line.
  4. **Contradicting evidence:** each supporting memory with its tags. **Highlight the foreign customer tag** (for example `customer:anvaya`).
  5. **Root cause:** `st.warning(root_cause)`. If `identity` is present, show a line: `"Kestrel Logistics ≡ Anvaya Technologies Pvt Ltd · confidence 0.92"` and the linking-evidence quote.
  6. **Blast radius:** `st.metric("Earlier answers that used this memory", n)`.
  7. **Recommended fix:** bullet list.
  8. **Buttons:**
     - **Apply fix** — disabled if the status is not `open` or the type is EXECUTION/UNKNOWN.
     - **Undo fix** — enabled only if the status is `fixed`.
     - **Re-ask question** — enabled if `fixed` and `question` is not None.
  9. **After re-ask:** two columns, **Before** (the wrong answer) and **After** (the re-ask answer plus its used memories). Show `st.success` if the new short answer differs from the wrong one.
  10. **Applied actions:** list them. Show invalidations as `"Invalidated in Hindsight: <memory id> (reversible)"`.

### Tab 3 — "Memory Health"
- If `eval_latest.json` exists:
  - a metrics row: accuracy before, accuracy after (with delta), wrong answers fixed, incidents by type;
  - `st.image("docs/before_after.png")`;
  - a per-question dataframe (`id`, customer, question, before ✓/✗, after ✓/✗, fixed_by).
- **Tier 3 section "What Memory SRE has learned":**
  - list `lessons.learned()` with their proof counts.
  - A **Run proactive scan** button, enabled only if `lessons.has_resolution_lesson()`. Caption: *"Applies the identity-split lesson learned from past incidents to find unlinked customers before they cause wrong answers."*
  - Show each proposal as a card: `"Saffron Retail ≡ Mehta Brothers Trading LLP"`, shared domain, evidence, confidence, and a **Link identities** button that calls `lessons.accept_proposal`. Then show `st.success("Prevented: linked before any wrong answer.")`.

**UI rules:**
- Wrap every backend call in `try/except`, showing `st.error(str(e))`.
- Never show API keys.
- Keep all business logic out of `app.py`: call only the `memsre.*` functions.

---

## 13. Scripts and tests

### `scripts/smoke.py`
Run `config.check()`, `hs.client().get_version()` (print `api_version`), then `llm_json(SRE_SYSTEM, 'Return {"ok": true}')`. Print `SMOKE OK`.

### `scripts/seed.py` (`--keep-lessons` optional)
1. `hs.reset_bank(MAIN_BANK_ID, name="Lumora Support Memory", retain_mission="Extract facts about customers of Lumora Cloud: plans and plan changes with effective dates, hosting regions, contacts and their email addresses, billing events, and support requests. Keep company and person names exactly as written.")`
2. Unless `--keep-lessons`: `hs.reset_bank(LESSONS_BANK_ID, name="Memory SRE Lessons", retain_mission="Extract lessons about how AI agent memory failed: the failure type, the detection signal, and the fix.")`
3. For each event in `events.jsonl`: `hs.retain_event(...)` as described in §7.3. Print progress `k/N`.
4. Write `tag_names.json` (`{"customer:<key>": customer_name}` for every event), then `store.reset_state()` and write `tag_names.json` again.
5. `hs.wait_for_idle(MAIN_BANK_ID, 300)`. Print `SEEDED <N> events`.

### `scripts/eval.py` (`--no-reset` optional)
1. Unless `--no-reset`, run the seed (same code path as `seed.py`, reset lessons).
2. **BEFORE:** for each question, `agent.answer(q.customer, q.question, q.format, run="eval-before")` then `grade()`.
3. **REPAIR:** iterate the questions that were wrong, in order. For each:
   - Re-ask (`run="eval-repair"`). If it is now correct, record `fixed_by = <last incident id>` and continue.
   - Otherwise `create_incident(ans, q.correction, q.format)`. If the type is not EXECUTION/UNKNOWN, `apply_fix`, and record `fixed_by = inc id` if the next re-ask is correct.
4. **AFTER:** re-answer all questions (`run="eval-after"`) and grade.
5. Write `data/results/eval_latest.json` (and `eval_<YYYYmmdd_HHMM>.json`):
   `{"before_accuracy", "after_accuracy", "n", "questions": [{id, customer, question, defect, before_correct, before_short, after_correct, after_short, fixed_by}], "incidents": [{id, failure_type, customer, answers_fixed}], "by_type": {type: count}}`.
6. **Chart** `docs/before_after.png` (matplotlib, 10×4 in, dpi 150):
   - Left subplot: two bars, "Before Memory SRE" and "After Memory SRE", accuracy % with value labels, y-axis 0–100.
   - Right subplot: horizontal bars, **wrong answers fixed per incident** (label `INC-001 · RESOLUTION`).
   - Suptitle: `"Memory SRE — support-agent accuracy on 20 questions"`.
7. Print a summary table.

**Expected (not guaranteed):** before ≈ 60% (Kestrel and Saffron questions wrong), after ≈ 95–100%. **Report the real numbers — never hardcode them.**

### Tests
- `tests/test_grading.py`:
  - `"1,000"` → `"1000"`; `"10000"` does not grade as `"1000"`;
  - `"4 hours"` → `"4h"`; `"730 days"` → `"730"`;
  - `"No, it isn't included"` → `"no"`; `"yes."` → `"yes"`.
- `tests/test_classify.py`: one test per branch of `classify()` (6 tests), using hand-built `Mem` objects.

---

## 14. Build order (with checkpoints)

Commit after every step: `git add -A && git commit -m "<step>"`.

| Step | Build | CHECK (must pass) |
|---|---|---|
| 0 | Hygiene (§3), `requirements.txt`, `.env.example`, `.gitignore` additions, install | `python -c "import hindsight_client, openai, streamlit"` |
| 1 | `config.py`, `llm.py`, `hs.py`, `scripts/smoke.py` | `python scripts/smoke.py` → `SMOKE OK` |
| 2 | Seed files (§7), `catalog.py`, `store.py`, `scripts/seed.py` | `python scripts/seed.py` → `SEEDED 26 events`; `hs.list_tags(MAIN,"customer:*")` shows 8 tags incl. `customer:anvaya`, `customer:mehta-bros` |
| 3 | `grading.py`, `agent.py` | `python -m memsre.agent kestrel "Can Kestrel Logistics export audit logs?"` → short answer **yes** (the defect reproduces) and the used memories include the June Enterprise fact. Also `python -m memsre.agent quartz "Which Lumora plan is Quartz Mobility on?"` → starter |
| 4 | `diagnose.py` + `classify()` | `python -m memsre.diagnose` → `failure_type == "RESOLUTION"`, `identity.foreign_tag == "customer:anvaya"`, and linking evidence mentions `anvaya.in` |
| 5 | `repair.py` | apply_fix, then reask → short answer **no**; undo_fix, then reask → **yes** again; apply_fix again leaves it fixed |
| **⏱ HARD CHECKPOINT** | **Steps 0–5 must work by ~23:00.** If not, skip Step 8 (Tier 3) entirely. | |
| 6 | `tests/*`, `scripts/eval.py` | `pytest` green; `python scripts/eval.py` writes `eval_latest.json` + `docs/before_after.png`; after > before |
| 7 | `app.py` (Tabs 1–3 without the Tier 3 section) | Manually run the demo beats 2–5 and 7 from §0 in the browser |
| 8 | **Tier 3:** `lessons.py`, plus the Tier 3 section of Tab 3 | After fixing the Kestrel incident in the UI, **Run proactive scan** proposes Saffron Retail ≡ Mehta Brothers Trading LLP; linking it fixes Q05 on re-ask |
| 9 | README (§16), final cleanup, `git push` | The repo on GitHub shows the README with the chart; `.env` is **not** in the repo |

---

## 15. Demo recording procedure (Tuesday morning)

1. `python scripts/eval.py` → the chart and results (about 20–30 min on Groq's free tier; go do something else meanwhile).
2. `python scripts/seed.py` → a fresh bank for the live demo. The chart file stays.
3. `streamlit run app.py`. In the **Support Console**, select **Kestrel Logistics**:
   1. Ask "What is Kestrel Logistics' API rate limit?" (wrong: 10000). **Don't** report it.
   2. Ask "Can Kestrel Logistics export audit logs?" → "Yes…" (wrong).
   3. 👎, then paste: *"Wrong — the customer says audit log export fails. They told us they moved to the Growth plan in August."* → **Report & diagnose**.
4. **Incidents tab:** show the culprit, the Anvaya evidence, the identity link via `ravi.k@anvaya.in`, root cause RESOLUTION, and blast radius 2. **Apply fix** → **Re-ask** → "No — Growth doesn't include audit log export."
5. **Memory Health tab:** the lessons learned → **Run proactive scan** → Saffron ≡ Mehta Brothers → **Link identities** → "Prevented".
6. Finish on the before/after chart.

---

## 16. README.md (write it; the judges read this first)

Sections, in order:
1. **Title + one-liner:** "Memory SRE — find the memory that made your agent wrong, and fix it. Built on Hindsight."
2. **Hero image:** `docs/before_after.png`, with one sentence of the real numbers from `eval_latest.json`.
3. **The problem (3 short paragraphs):**
   - agents with long-term memory fail in new ways;
   - when an answer is wrong, nobody can tell whether the model or the memory caused it;
   - Hindsight shows *what* was recalled, but not *whether it caused the failure*.
4. **What Memory SRE does:** diagnose → evidence → classify → repair (reversible) → verify → learn.
5. **Failure taxonomy table:** the six types, with a one-line definition and the automatic fix.
6. **Architecture:** a mermaid diagram:
   ```mermaid
   flowchart LR
     Rep[Support rep] --> Agent[Support agent] -->|recall any_strict| HS[(Hindsight bank)]
     Rep -- 👎 + correction --> SRE[Memory SRE]
     SRE -->|culprit + whole-bank evidence recall| HS
     SRE -->|classify| Tax{Failure type}
     Tax -->|RESOLUTION| Link[Link identities + invalidate superseded memory]
     Link --> HS
     SRE -->|post-mortem| LB[(Lessons bank)]
     LB -->|proactive identity scan| SRE
   ```
7. **How Hindsight memory is used** (explicit; this is graded):
   - **retain** with timestamps, `document_id`, metadata and per-source `customer:*` tags (`scripts/seed.py`, `memsre/hs.py`);
   - **recall** scoped with `tags_match="any_strict"` for the agent, and **whole-bank recall** for evidence search (`memsre/agent.py`, `memsre/diagnose.py`);
   - **curation API**: invalidate / restore memories reversibly, after which Hindsight re-computes derived observations (`memsre/repair.py`);
   - **documents API** to remove repair artifacts on undo;
   - **operations API** to wait for consolidation;
   - **a second bank of lessons**: every incident post-mortem is retained, and Hindsight's consolidation turns them into observations with proof counts, which drive the proactive scan (`memsre/lessons.py`).
8. **Quickstart:** venv, `pip install -r requirements.txt`, fill `.env`, `python scripts/smoke.py`, `python scripts/seed.py`, `streamlit run app.py`, `python scripts/eval.py`.
9. **Demo walkthrough:** §15 steps 3–6.
10. **Limitations (honest):**
    - The demo data is a fictional company.
    - The defects are realistic but planted.
    - Diagnosis needs a correction from a human.
    - Identity linking relies on concrete evidence such as email domains.
    - EXECUTION failures are reported, not auto-fixed.
11. **What's next:**
    - continuous monitoring with a memory health score;
    - more failure types (WRITE extraction errors, cross-scope leaks);
    - Microsoft Agent Framework integration and Teams alerts;
    - a Hindsight webhook trigger on consolidation.
12. **Credits:** Hindsight ([github.com/vectorize-io/hindsight](https://github.com/vectorize-io/hindsight)), Groq. Note that all companies and people are fictional.

---

## 17. Troubleshooting

- **T1 — Step 3 says "no" instead of "yes" (the defect doesn't reproduce).**
  - Print the recalled memories. Every memory must carry a `customer:kestrel` tag.
  - If the billing fact appears, the tag filter isn't applied: make sure `tags_match="any_strict"` is passed and `tags` is non-empty.
- **T2 — Groq 429 or slow.**
  - The limiter and retries handle it; wait it out.
  - Put a teammate's key in `GROQ_API_KEYS` to double throughput.
  - For quick UI testing only, set `GROQ_MODEL=openai/gpt-oss-20b`.
- **T3 — Groq 400 on a parameter.** `llm.py` must auto-retry without `reasoning_effort` / `response_format` / `max_completion_tokens` (§6.2).
- **T4 — Empty `content` from the model.** Raise `max_completion_tokens` to 2000 (reasoning tokens can consume the budget).
- **T5 — Hindsight timeouts on retain.** Increase the client timeout to 180 s. `retain_event` retries once.
- **T6 — `create_bank` fails because the bank exists.** `reset_bank` deletes first; ignore 404 on delete.
- **T7 — `wait_for_idle` never returns True.** It returns False after the timeout; continue anyway.
- **T8 — `list_memories` response shape differs.** Print one raw response and adapt the field names. Expected: `items[]` with `text`, `proof_count`.
- **T9 — The identity check returns `same_customer=false` for Kestrel/Anvaya.**
  - Print `facts_a` / `facts_b`. Both must include an `@anvaya.in` email.
  - If Hindsight's extraction dropped the email, add it to the recall query (`"email address"`) or increase `max_tokens` to 1500.

---

## 18. Final checklist before submitting

- [ ] `pytest` green
- [ ] `python scripts/eval.py` run once, chart committed
- [ ] The full demo (§15) works end to end in Streamlit
- [ ] README complete, including **"How Hindsight memory is used"**
- [ ] `git log` has no `.env`; `git grep -n "gsk_\|hsk_"` returns nothing
- [ ] Pushed to `https://github.com/079Sathya/hindsight-agent` (public)
