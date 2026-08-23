# Architecture — Frequency Lead Intelligence Agent

One-page note for the GTM take-home.

## What it does

A single LangGraph researcher turns an ICP into a human review queue.

```text
parse ICP → expand queries → public search → extract companies
→ cluster / exclude clients → enrich + verify signals
→ contact policy → score → match proofs → draft + QA → SQLite queue
```

Prototype trigger: **Run agent**. Production trigger: a daily job that only processes **new signals since last run**, then the same queue.

## Autonomous vs human

**Autonomous:** search, discovery, enrichment, verification, scoring, dedup, proof-point matching, drafting, QA, memory writes.

**Human-gated:** approve, edit, reject, enqueue to the dry-run send queue, dry-run dispatch, hold. The agent never sends. Dry-run writes `output/dry_run_send_log.jsonl` only — no SMTP, LinkedIn, or WhatsApp.

## Why this shape

Frequency's differentiation is precision. A 15-microservice multi-agent would score poorly on judgment. One stateful graph is explainable in an interview: each node is a step a researcher already takes.

The LLM is restricted to extraction and prose. Numbers, names, and dates must appear in source text or they are marked inferred and blocked from sendable copy.

## Service lines

Playbooks change **what a good lead is** and **who to address**:

- Exec search → founder/CEO, or CHRO/TA if the signal is recruiting-heavy
- Fractional CXO → founder/CEO (buyer of fractional help)
- Capital advisory → founder/CEO/CFO on a capital decision, not a vanity raise

## Memory

SQLite stores domain, signal hash, score, review status, do-not-contact. Same signal is not re-drafted. New HIGH signal on a known company updates the lead. Rejects persist.

## What we'd build next

CRM write-back · scheduled runs · reviewer-feedback weights · richer public contact graph · capital-specific proof pack · dry-run send log into a real ESP in sandbox mode.
