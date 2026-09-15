# Frequency Lead Intelligence Agent

Autonomous **public-web lead research** prototype for [Frequency](https://frequency.cx) GTM. It turns Frequency’s manual BD motion — find companies → research a live signal → draft hook + proof + CTA — into a **human-reviewed** research agent.

**Nothing sends automatically.** The agent searches public sources, verifies signals, scores leads with explainable arithmetic, matches Frequency proof points, finds decision-maker contacts, drafts outreach, and stages everything for approve / edit / reject. Even “send” is **dry-run only** (JSONL log, no SMTP, no LinkedIn API).

---

## Table of contents

1. [Problem & design principles](#problem--design-principles)
2. [Tech stack](#tech-stack)
3. [Quick start](#quick-start)
4. [Architecture overview](#architecture-overview)
5. [Query-centric data model](#query-centric-data-model)
6. [Research pipeline (LangGraph)](#research-pipeline-langgraph)
7. [Lead scoring metrics](#lead-scoring-metrics)
8. [Signal verification](#signal-verification)
9. [Contact discovery & LinkedIn validation](#contact-discovery--linkedin-validation)
10. [Contact relevance scoring (per person)](#contact-relevance-scoring-per-person)
11. [Frequency proof-point matching](#frequency-proof-point-matching)
12. [Interest briefs](#interest-briefs)
13. [Outreach drafting & QA gate](#outreach-drafting--qa-gate)
14. [Persistence (SQLite)](#persistence-sqlite)
15. [Streamlit UI](#streamlit-ui)
16. [Exports & enrichment tray](#exports--enrichment-tray)
17. [Dry-run send queue](#dry-run-send-queue)
18. [Configuration & environment](#configuration--environment)
19. [Static data files](#static-data-files)
20. [Project structure](#project-structure)
21. [Tests](#tests)
22. [Limitations & honest gaps](#limitations--honest-gaps)
23. [Future work](#future-work)

---

## Problem & design principles

Frequency’s BD is senior-led and precise. The bottleneck is research: who just raised, who is expanding, who has a leadership gap, and whether Frequency has an honest analogue. This agent automates **that slice** and stops before anything goes out.

| Principle | Implementation |
|-----------|----------------|
| **LLM extracts; code verifies** | Structured Pydantic outputs from the LLM; deterministic scoring, signal verification, and QA gates |
| **Never invent facts** | Missing fields → `unknown` / `not_found`; weak signals → `[BLOCKED — DO NOT SEND]` drafts |
| **Public sources only** | Tavily/DDG search + page fetch; no LinkedIn login, no Apollo/DAG API scraping |
| **Human in the loop** | Approve / edit / reject; dry-run queue only |
| **Explainability** | Every score shows component arithmetic + reason strings |
| **Per-query dedup** | Same company can appear in different ICP queries; within one query, fetch-more never repeats |

---

## Tech stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11+ |
| Orchestration | [LangGraph](https://github.com/langchain-ai/langgraph) — linear 6-node state machine |
| LLM | OpenAI — `gpt-4o-mini` (extract/parse), `gpt-4o` (outreach + interest briefs) |
| Search | [Tavily](https://tavily.com) (primary), DuckDuckGo (fallback) |
| Fetch | httpx, trafilatura, BeautifulSoup |
| Schemas | Pydantic v2 |
| Storage | SQLite (`FREQUENCY_DB_PATH` or `frequency_agent.db`) |
| UI | Streamlit |
| Tests | pytest (29 tests) |

---

## Quick start (Docker)

The agent runs in a Linux container that matches production. Feature work, tests, and deploys all use this image.

```bash
cd frequency-lead-agent
copy .env.example .env          # paste OPENAI_API_KEY and TAVILY_API_KEY
docker compose up --build
```

Open `http://localhost:8501`. Source is bind-mounted: save a file and Streamlit reruns inside the container.

| Task | Command |
|------|---------|
| App | `docker compose up --build` |
| Tests | `docker compose exec agent python -m pytest tests -q` |
| Shell | `docker compose exec agent bash` |
| CLI run | `docker compose exec agent python run_agent.py --icp "Series B+ fintech in India"` |
| New dependency | add to `requirements.txt`, then `docker compose up --build --watch` (or rebuild) |
| Deploy | `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` |

SQLite lives at `/app/var/frequency_agent.db` (host folder `var/` in local compose). Output CSVs stay in `output/`.

**Without Docker** (venv):

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
python -m pytest tests -q
```

---

## Architecture overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                         Streamlit UI (app.py)                           │
│  New query │ Fetch more │ Review queue │ All queries │ Apollo/DAG │ Send│
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    LangGraph pipeline (graph.py)                        │
│                                                                         │
│  parse_icp → expand_queries → search_web → extract_companies → cluster  │
│       → enrich (verify, score, contacts, proofs, draft, persist)        │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
   SearchClient              LLM (extract/draft)         Memory (SQLite)
   Tavily / DDG              Pydantic schemas            query_sessions
   fetch + page cache        scoring / verify            leads, runs, queue
```

**Module reload:** On each Streamlit load, `app.py` reloads `memory`, `extract`, `contacts`, and `graph` so code changes apply without restarting the Python process (fixes stale-module issues during development).

---

## Query-centric data model

The latest version organizes work around **query sessions**, not global ICP dedup.

### Concepts

| Term | ID | Meaning |
|------|-----|---------|
| **Query session** | `query_id` (12-char hex) | One ICP you entered — stable container for all fetches |
| **Fetch / run** | `run_id` (12-char hex) | One click of **New query** or **Fetch more** |
| **Lead** | `lead_id` (slug from domain + name) | One company record with full JSON payload |

### Dedup rules

- **Within a query:** `Fetch more` skips companies already linked in `query_leads` for that `query_id` (by domain or normalized name).
- **Across queries:** The **same company may appear again** in a different query session — overlap is allowed by design.
- **Client exclusions:** Companies in `data/exclude_domains.json` (Frequency’s own clients) are always skipped.

### UI actions

| Button | Behavior |
|--------|----------|
| **New query** | `memory.create_query_session()` → new `query_id` → full pipeline run |
| **Fetch more** | Reuses `active_query_id` → pipeline with `seen_for_query()` populated |
| **Clear all results** | Wipes leads, queries, runs, send queue (sidebar) |
| **All queries & results** | Unified timeline: every query, fetch timestamps, companies, discovery web query per lead |

After each run, the review queue loads **`memory.leads_for_query(query_id)`** — all companies ever linked to that query, combined across fetches.

---

## Research pipeline (LangGraph)

Defined in `frequency_agent/graph.py`. State is `AgentState` (TypedDict): ICP, hits, clusters, leads, funnel, `query_id`, logs, etc.

```text
START → parse_icp → expand_queries → search_web → extract_companies → cluster → enrich → END
```

### Node 1: `parse_icp`

- LLM parses free-text ICP → structured `ICP` (geo, cities, sectors, stages, recency_days, buying_signals, …).
- **Infers `service_line`** (`exec_search`, `fractional_cxo`, or `capital_advisory`) from the brief — no manual picker in the UI.
- Computes `icp_hash` (metadata fingerprint; not used for global dedup).
- If `query_id` present: loads `memory.seen_for_query(query_id)` → `seen_domains`, `seen_names`.
- Creates `run_id`, `run_started`, initial funnel counters.

### Node 2: `expand_queries`

- **Template queries** from ICP (`search.template_queries`) — funding, appointments, expansion, hiring, GCC/capital variants.
- LLM adds up to 4 more queries (`QuerySet` schema).
- **Cap: 10 unique queries** per run.

### Node 3: `search_web`

- `SearchClient.search()` per query — **5 results** each, `advanced=True` for discovery pass.
- Dedupes URLs; optional Tavily `country=india` when geo mentions India.
- Blocked: LinkedIn login, Facebook, Instagram, Twitter intent URLs.
- Typical yield: **30–50 unique URLs** per run.

### Node 4: `extract_companies`

- Batches hits (4 at a time) to LLM extractor (`extract.extract_from_hits`).
- Output: `ExtractedOrg` per mention — name, signal, evidence quote, `source_url`, `discovery_web_query`.
- Only keeps `is_relevant_to_icp == true`.
- **Does not invent** funding amounts, dates, or websites.

### Node 5: `cluster`

- Merges mentions by domain (or normalized name if domain unknown).
- Skips Frequency client exclusions + per-query seen companies.
- Tracks **`discovery_web_query`** — which expanded search query first surfaced the company.
- Funnel metric: `skipped_this_run` = duplicates within query.

### Node 6: `enrich` (per company cluster)

Capped by `MAX_DISCOVER` (default **22** companies per fetch).

For each cluster:

1. **Company-specific search** — `"{name}" {geo} funding OR raised OR appointed OR expansion OR hiring {sector}`
2. **Page fetch** — `fetch_text()` with SQLite `page_cache`
3. **LLM enrich** — `enrich_company()` → website, stage, signal fields, optional contact from article
4. **Multi-contact discovery** — `discover_contacts_for_lead()` (see §Contact discovery)
5. **Signal verify** — `verify_signal()` against corpus
6. **Score** — `score_lead()` deterministic breakdown
7. **Proof match** — top 3 from `proof_points.json`
8. **Interest brief** — `explain_interest()` LLM paragraph
9. **Outreach draft** — email + LinkedIn note if signal usable; else blocked
10. **Persist** — `upsert_lead`, `link_lead_to_query`, `save_run`, `write_search_csv`

**Queue selection:** Up to `MAX_QUEUE` (default **15**) leads returned to UI, prioritizing `usable_in_outreach` signals.

### Funnel metrics (UI)

| Metric | Meaning |
|--------|---------|
| Queries | Expanded search queries count |
| URLs | Unique search result URLs |
| New cos | Companies after cluster (new to this query) |
| Skipped | Already linked to this query |
| Usable | Signals cleared HIGH/MEDIUM for outreach |
| Queued | Leads returned to review queue |

---

## Lead scoring metrics

**File:** `frequency_agent/scoring.py`  
**Rule:** The LLM never picks the score. All points are deterministic.

**Total = ICP fit (max 40) + Signal strength (max 25) + Recency (max 20) + Contact relevance (max 15)**

### ICP fit (max 40 points)

| Condition | Points |
|-----------|--------|
| Sector match (ICP sectors in industry/name/signal blob) | +12 |
| No sectors in ICP | +6 partial |
| Sector in ICP but no match | +0 |
| Geo match (country/city vs ICP geo/cities) | +10 |
| Country unknown | +4 (not assumed) |
| Geo mismatch | +0 |
| Stage language match (Series B/C/D, ICP stages) | +10 |
| No stages in ICP | +5 |
| Stage not explicit in sources | +3 |
| Public website resolved | +8 |
| Website not_found | +0 |

### Signal strength (max 25 points)

**Strong signal types:** `funding`, `leadership_departure`, `new_executive`, `expansion`, `hiring_surge`, `new_business_line`, `acquisition`, `product_launch`

| Condition | Points |
|-----------|--------|
| Strong signal type | +15 |
| Other non-none type | +8 |
| Weak / none / other | +3 |
| Confidence HIGH | +10 |
| Confidence MEDIUM | +6 |
| Confidence LOW | +2 |
| Confidence UNVERIFIED | +0 |

### Recency (max 20 points)

Uses signal date vs ICP `recency_days` (default **90**).

| Condition | Points |
|-----------|--------|
| ≤ 30 days ago | +20 |
| ≤ recency window (e.g. 90d) | +14 |
| ≤ 2× recency window | +6 |
| Older / stale | +0 |
| Date unknown | +6 (not treated as fresh) |

### Contact relevance (max 15 points)

| Condition | Points |
|-----------|--------|
| Named + usable primary contact | +15 |
| Named but lower confidence | +9 |
| Role suggested, name not_found | +7 |
| Inferred name | +2 |
| Default / none | +3 |
| ≥2 usable named decision-makers | +1–3 bonus (capped in 15) |
| Public email on file | +2 reachability |
| Public phone on file | +2 |
| LinkedIn URL only | +1 |

The review pane shows every line in `score.reasons[]` plus a one-line `score.why` summary.

---

## Signal verification

**File:** `frequency_agent/verify.py`

The LLM extracts signals; **code** decides if they are outreach-safe.

### Verification steps

1. **Quote support** — `evidence_quote` or `summary` must appear in fetched corpus (substring or SequenceMatcher ratio > 0.22).
2. **Recency** — parsed via multiple date formats; stored in `signal.recency_days`.
3. **Publisher check** — known business press domains boost confidence (Economic Times, Inc42, YourStory, TechCrunch, Mint, Reuters, Entrackr, The Ken, VCCircle, etc.).
4. **Confidence assignment:**

| Condition | Confidence | Usable in outreach? |
|-----------|------------|---------------------|
| Strong type + named publisher + date ≤ 180d + supported | **HIGH** | Yes |
| Strong type + supported | **MEDIUM** | Yes |
| Otherwise supported | **LOW** | No |
| Not supported / no signal | **UNVERIFIED** | No |

Unusable signals produce `[BLOCKED — DO NOT SEND]` drafts and cannot enter the send queue.

---

## Contact discovery & LinkedIn validation

### Who we target (`contact_policy.py`)

**Included:** Founders, CEOs, CFOs, CHROs, Heads of Talent/HR, VPs, Directors — people who can **approve** exec search, fractional CXO, or capital advisory work.

**Excluded:**

- Journalists, reporters, authors, editors, columnists
- Press/PR/spokespersons, media relations
- Investors, VCs, board members **at other firms** quoted in articles
- “Company name as person” extractions
- LinkedIn post authors who are not executives

**Gate:** `validate_outreach_contact()` requires:

- Decision-maker title (`is_decision_maker_role`)
- Not in excluded categories (`is_excluded_contact`)
- Name + role + company co-occur in source text within ~220 characters (`person_at_company_in_text`)

### Discovery flow (`contacts.py`)

1. **Seed** from enrichment extract (person named in signal article).
2. **LLM multi-contact extract** from corpus — strict prompt: target company only, decision-makers only (`extract_contacts_from_corpus`).
3. **Extra leadership searches** if &lt;2 usable contacts — queries from `data/playbooks.json` `signal_to_contact` map.
4. **Per-person channel enrichment** — regex + targeted searches for email, phone, LinkedIn, X.
5. **Rank** — reachability then `relevance_score`; primary = rank #1.

**Playbook example (exec_search + hiring_surge):** preferred contacts = CHRO → Head of Talent → Founder → CEO.

### LinkedIn rules (`channels.py`)

**Never** fetch LinkedIn HTML (login wall). URLs come only from public text or search result titles/snippets.

**`linkedin_matches_person()` requires ALL of:**

| Check | Detail |
|-------|--------|
| Valid `/in/` or `/pub/` URL | Rejects `/company/`, `/posts/`, search URLs |
| Name ↔ slug | First/last name tokens in URL slug |
| Company in context | Company name or domain token in surrounding text |
| Role in context | Title matches (CEO ↔ “founded”, etc.) |
| Not excluded role | Press/investor patterns rejected |

Failed LinkedIn URLs are **dropped**, not shown.

### Channel priority

```
email (100) > phone (95) > LinkedIn (80) > X/Twitter (60) > other (30)
```

Company-domain emails preferred; generic `info@` rejected unless tied to the person.

---

## Contact relevance scoring (per person)

Within `contacts._candidate_from_raw`, each person gets a **relevance_score** (separate from lead score):

| Factor | Points (typical) |
|--------|------------------|
| Role matches playbook for service line + signal | +8 to +40 (earlier in list = higher) |
| Adjacent role | +4 |
| Name sourced in public text | +25 |
| Name inferred | +2 |
| Name weakly sourced | +6 |
| Confidence HIGH / MEDIUM / LOW / UNVERIFIED | +15 / +10 / +4 / +0 |
| Mentioned in signal context | +12 |
| Hiring signal + talent/HR role | +10 |
| Funding signal + founder/CEO | +10 |
| Leadership departure + backfill owner | +10 |
| Public email found | +18 |
| Public phone | +14 |
| LinkedIn URL | +12 |
| X/Twitter | +6 |

Candidates failing `validate_outreach_contact` return `None` and are not listed.

---

## Frequency proof-point matching

**File:** `frequency_agent/proofs.py`  
**Data:** `data/proof_points.json`

Tag-based matching — LLM does **not** pick from the full deck.

1. Tokenize lead + ICP into tags (fintech, saas, series_b, gcc, india, hr, …).
2. Score each proof point by tag overlap + service-line bias from playbooks.
3. Return top **k=3** matches with `why_matched` string.

Outreach QA requires **≥2 matched proof names** cited in the email draft.

---

## Interest briefs

**File:** `frequency_agent/interest.py`

After scoring and proof matching, an LLM generates **`why_interested`** — a 4–6 sentence BD brief covering:

1. What signal makes timing plausible now  
2. Which leadership/talent/capital gap Frequency could help with  
3. Why matched proof points are relevant (no invented outcomes)  
4. Who should care internally if contact name is missing  

Facts-only; no flattery or invented numbers. Shown in the review detail pane under **“Why they might be interested in Frequency”**.

---

## Outreach drafting & QA gate

**File:** `frequency_agent/outreach.py`  
**Tone:** `data/tone_guide.json` — Precision, Poise, Intrigue

### Channels

| Channel | Role |
|---------|------|
| **Email** | Primary first-touch (110–190 words target) |
| **LinkedIn note** | Secondary, shorter (60–95 words) |
| **WhatsApp** | Not used for CXO first-touch |

### Draft generation

- Model: `gpt-4o` (`LLM.draft_model`)
- Structure: hook (signal) → proof points → low-friction CTA
- If signal not usable: both drafts = `[BLOCKED — DO NOT SEND]`

### QA flags (`qa_outreach`)

Automated checks before human review:

- Banned phrases from tone guide (“I hope this email finds you well”, “synergy”, …)
- Email word count outside range
- Fewer than 2 Frequency proof points cited
- Hook does not reference sourced signal tokens
- Unsourced numbers (₹, crore, million, etc.) not in signal/proof text
- Missing or high-friction CTA
- Inferred contact name used as fact
- Signal not cleared for outreach

Flags set `review_status: needs_edit` when present.

---

## Persistence (SQLite)

**File:** `frequency_agent/memory.py`  
**Database:** `frequency_agent.db` (project root by default; `FREQUENCY_DB_PATH` in Docker → `/app/var/frequency_agent.db`)

### Tables

| Table | Purpose |
|-------|---------|
| `query_sessions` | ICP text, service line, created/last_run, label |
| `query_leads` | Links query_id ↔ lead_id + discovery_web_query + run_id + linked_at |
| `leads` | Full `payload_json`, review_status, score, do_not_contact |
| `runs` | Funnel, queries, logs, lead_ids, csv_path, query_id |
| `run_leads` | Run ↔ lead association |
| `page_cache` | Fetched URL text (avoids re-fetch) |
| `send_queue` | Dry-run queue items |
| `review_events` | Approve/reject/edit audit trail |

### Key API methods

| Method | Purpose |
|--------|---------|
| `create_query_session(icp)` | New query (service line filled after first parse) |
| `seen_for_query(query_id)` | Per-query dedup set |
| `link_lead_to_query(...)` | Attach lead to query |
| `leads_for_query(query_id)` | All companies for one query |
| `unified_results()` | All queries + leads for history tab |
| `clear_all_data()` | Wipe and start fresh |
| `upsert_lead` / `save_run` | Persist after enrich |

---

## Streamlit UI

**File:** `app.py` + `frequency_agent/ui.py`

### Main controls

- **What are you looking for?** — single plain-language brief (service line inferred by AI)
- **Example brief (optional)** — quick-start presets
- **New query** / **Fetch more**

### Tabs

| Tab | Purpose |
|-----|---------|
| **Review queue** | Lead list, detail pane, approve/edit/reject/queue |
| **All queries & results** | Unified history with timestamps and company tables |
| **Apollo / DAG enrich** | Browser extension tray — CSV, LinkedIn URL list, search fallbacks |
| **Dry-run send queue** | Queue, hold, dry-run dispatch → JSONL log |

### Review detail pane shows

- Score breakdown + reasons  
- **Why they might be interested in Frequency**  
- Discovery web query + query session ID  
- Signal + sources + evidence quote  
- Ranked contacts with channels (email, phone, LinkedIn, X)  
- Matched proof points  
- Email draft + LinkedIn note  
- QA flags + field uncertainty  

### Sidebar

- API key status (OpenAI / Tavily)  
- Memory stats (leads, queries, fetches)  
- Load saved query / recent fetch  
- Download CSVs  
- **Clear all results**  

---

## Exports & enrichment tray

| Output | Path / trigger | Contents |
|--------|----------------|----------|
| Per-fetch contacts CSV | `output/searches/{run_id}_....csv` | Auto-written after each enrich |
| Sample output | `output/sample_output.csv` | Sidebar download / CLI |
| Apollo/DAG CSV | `output/apollo_dag_enrich.csv` | People rows for browser extensions |
| LinkedIn URL list | `output/linkedin_profiles.txt` | One URL per line |
| Apollo search fallback | `output/apollo_search_fallback.txt` | Name \| Company \| Domain when no LinkedIn |
| Dry-run log | `output/dry_run_send_log.jsonl` | What would have been “sent” |

**Apollo / DAG workflow:** Install extension in Chrome → open LinkedIn URLs from export → extension fills email/phone. The app never logs into LinkedIn or Apollo/DAG.

---

## Dry-run send queue

**File:** `frequency_agent/send_queue.py`

| Step | Behavior |
|------|----------|
| Approve / Queue dry-run | `can_enqueue()` checks review status, usable signal, non-blocked draft |
| Dry-run send | Writes JSONL record; sets `outreach_status: dry_run_sent` |
| Reject | `do_not_contact=1`; held items in queue |
| Hold | Status `held` — not dispatched |

**Nothing is delivered** to a real inbox or LinkedIn.

---

## Configuration & environment

### `.env`

```env
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...
```

Tavily optional — falls back to DuckDuckGo (lower quality for Indian business press).

### Environment variables

| Variable | Default | Effect |
|----------|---------|--------|
| `MAX_DISCOVER` | `22` | Max companies enriched per fetch |
| `MAX_QUEUE` | `15` | Max leads returned to UI queue |
| `SEARCH_WORKERS` | `6` | Parallel Tavily/DDG queries |
| `FETCH_WORKERS` | `10` | Parallel page fetches |
| `LLM_WORKERS` | `4` | Parallel extract batches |
| `ENRICH_WORKERS` | `5` | Parallel company enrichment |
| `CONTACT_WORKERS` | `4` | Parallel per-person channel lookup |

### Performance

The pipeline parallelizes I/O-bound work without changing scoring, verification, or contact policy:

- **Search** — all 10 discovery queries run concurrently
- **Fetch** — page cache + pooled HTTP per thread; batch prefetch before extract/enrich
- **Extract** — LLM company/contact batches in parallel
- **Enrich** — multiple companies enriched at once; interest brief + outreach draft run concurrently per lead
- **Contacts** — top candidates channel-searched in parallel; early exit when email + LinkedIn found

Typical speedup: **2–4×** on a full run vs the serial pipeline (depends on API latency and `ENRICH_WORKERS`).

### LLM models (`llm.py`)

| Use | Model | Temperature |
|-----|-------|-------------|
| Parse / extract | `gpt-4o-mini` | 0 |
| Outreach drafts | `gpt-4o` | 0.4 |
| Interest brief | `gpt-4o-mini` | 0.35 |

---

## Static data files

| File | Purpose |
|------|---------|
| `data/icp_presets.json` | Streamlit ICP preset labels + text |
| `data/playbooks.json` | Service-line contact policy, signal→contact mapping, proof bias |
| `data/exclude_domains.json` | Frequency client domains/names to skip as new targets |
| `data/proof_points.json` | Frequency case studies for matching |
| `data/tone_guide.json` | Brand voice, banned phrases, word ranges, CTA examples |

### Service lines & contact policy (playbooks)

| Service line | Good lead | Preferred contacts |
|--------------|-----------|-------------------|
| **exec_search** | Leadership gap, VP+/CXO hiring, funding → team build | Founder, CEO, CHRO, Head of Talent |
| **fractional_cxo** | Scaling co. with functional gap (finance, product, GTM, tech, HR) | Founder, CEO |
| **capital_advisory** | Capital decision: expansion, acquisition, structured credit, raise | Founder, CEO, CFO |

**Signal→contact examples:**

- `hiring_surge` → CHRO, Head of Talent (exec_search)  
- `funding` → Founder, CEO (exec_search); Founder, CEO, CFO (capital_advisory)  
- `leadership_departure` → Founder, CEO, CHRO  

---

## Project structure

```text
frequency-lead-agent/
├── app.py                      # Streamlit UI
├── run_agent.py                # CLI runner
├── requirements.txt
├── Dockerfile                  # Production Linux image (Python 3.11)
├── docker-compose.yml          # Shared service
├── docker-compose.override.yml # Local: bind-mount source + live reload
├── docker-compose.prod.yml     # Deploy: named volumes, no source mount
├── docker-entrypoint.py
├── .env.example
├── var/frequency_agent.db      # SQLite in Docker (created at runtime)
├── frequency_agent/
│   ├── graph.py                # LangGraph 6-node pipeline
│   ├── memory.py               # SQLite + query sessions
│   ├── schemas.py              # Pydantic contracts
│   ├── llm.py                  # OpenAI wrapper
│   ├── search.py               # Tavily / DDG + query expansion
│   ├── fetch.py                # Page fetch + cache
│   ├── extract.py              # Company + contact LLM extraction
│   ├── contacts.py             # Multi-contact discovery + ranking
│   ├── contact_policy.py       # Decision-maker vs press/investor gates
│   ├── channels.py             # Email/phone/social + strict LinkedIn match
│   ├── verify.py               # Signal verification
│   ├── scoring.py              # Deterministic lead scoring
│   ├── proofs.py               # Proof-point matching
│   ├── interest.py             # Why-interested briefs
│   ├── outreach.py             # Draft + QA
│   ├── send_queue.py           # Dry-run queue logic
│   ├── export.py               # sample_output.csv
│   ├── search_export.py        # Per-fetch contacts CSV
│   ├── plugin_export.py        # Apollo/DAG tray
│   └── ui.py                   # Streamlit HTML/CSS
├── data/                       # Presets, playbooks, exclusions, proofs, tone
├── output/                     # CSVs, exports, dry-run log
└── tests/                      # pytest suite (29 tests)
```

---

## Tests

```bash
python -m pytest tests -q
```

| Test file | Covers |
|-----------|--------|
| `test_scoring.py` | Score arithmetic |
| `test_channels.py` | LinkedIn strict match, channel priority, malformed URLs |
| `test_contacts.py` | Role ranking, hiring signal contact preference |
| `test_contact_policy.py` | Press/investor exclusion, employer validation |
| `test_persistence.py` | Query sessions, per-query dedup, clear_all, CSV export |
| `test_outreach_qa.py` | QA flag rules |
| `test_proofs.py` | Proof matching |
| `test_send_queue.py` | Enqueue gates |

---

## Limitations & honest gaps

- **Contacts are public-only.** Many right people will be `not_found` by name; the agent suggests the role and will not invent a person.
- **Search quality** depends on Tavily coverage of Indian business press; DDG fallback is weaker.
- **LinkedIn URLs** are only accepted when public snippets tie name + role + company — many valid profiles will be omitted if search snippets are thin.
- **Strict contact policy** may yield fewer contacts per company vs loose extraction — intentional tradeoff for outreach quality.
- **Known Frequency clients** excluded as new BD targets (`exclude_domains.json`).
- **No CRM integration**, daily cron, or reviewer-feedback loop in this prototype.
- **CLI runner** does not create query sessions (UI path is the full query-centric experience).

---

## Future work

Designed but not built in this prototype:

- Scheduled re-fetch / cron per query session  
- CRM write-back (HubSpot, Salesforce)  
- Reviewer feedback → scoring calibration  
- Optional LinkedIn enrichment API (with explicit user auth)  
- Multi-user / team review queues  
- Real send integration (SMTP, LinkedIn API) behind explicit opt-in  

---

## License & context

Built as a GTM take-home prototype for Frequency. For internal evaluation and demonstration — not production GTM automation without further hardening.

**Frequency brand:** [frequency.cx](https://frequency.cx) — executive search, fractional CXO, capital advisory.
