"""Pydantic contracts. Missing facts are unknown / not_found — never invented."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ServiceLine = Literal["exec_search", "fractional_cxo", "capital_advisory"]
Confidence = Literal["HIGH", "MEDIUM", "LOW", "UNVERIFIED"]
FieldStatus = Literal["found", "unknown", "inferred", "not_found"]
SignalType = Literal[
    "funding",
    "leadership_departure",
    "new_executive",
    "expansion",
    "hiring_surge",
    "new_business_line",
    "acquisition",
    "product_launch",
    "other",
    "none",
]


class ICP(BaseModel):
    raw_text: str
    service_line: ServiceLine = "exec_search"
    geo: str = "India"
    cities: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)
    recency_days: int = 90
    company_types: list[str] = Field(default_factory=list)
    buying_signals: list[str] = Field(default_factory=list)
    target_contacts: list[str] = Field(default_factory=list)
    notes: str = ""


class SearchHit(BaseModel):
    query: str
    url: str
    title: str = ""
    snippet: str = ""
    published_date: str = ""
    raw_content: str = ""


class Source(BaseModel):
    url: str
    title: str = ""
    date: str = ""
    publisher: str = ""
    snippet: str = ""


class Signal(BaseModel):
    type: SignalType = "none"
    summary: str = ""
    date: str = "unknown"
    recency_days: int | None = None
    sources: list[Source] = Field(default_factory=list)
    confidence: Confidence = "UNVERIFIED"
    usable_in_outreach: bool = False
    evidence_quote: str = ""
    inferred: bool = False
    inferred_reason: str = ""


class ContactChannel(BaseModel):
    """A public reachability channel for a person or company."""

    kind: Literal["email", "phone", "linkedin", "twitter", "other"] = "other"
    value: str
    source_url: str = ""
    confidence: Confidence = "MEDIUM"
    priority: int = 0


class Contact(BaseModel):
    name: str = "not_found"
    role: str = "unknown"
    why: str = ""
    source_url: str = ""
    confidence: Confidence = "UNVERIFIED"
    usable_in_outreach: bool = False
    inferred: bool = False
    email: str = ""
    phone: str = ""
    linkedin_url: str = ""
    twitter_url: str = ""
    other_social: list[str] = Field(default_factory=list)
    channels: list[ContactChannel] = Field(default_factory=list)
    best_channel: str = ""


class ContactCandidate(Contact):
    """Ranked outreach target discovered from public sources."""

    relevance_score: int = 0
    rank: int = 0
    likelihood_reason: str = ""
    is_primary: bool = False
    apollo_hint: str = ""


class ScoreBreakdown(BaseModel):
    icp_fit: int = 0
    signal_strength: int = 0
    recency: int = 0
    contact_relevance: int = 0
    total: int = 0
    reasons: list[str] = Field(default_factory=list)
    why: str = ""


class ProofMatch(BaseModel):
    id: str
    company: str
    roles_placed: list[str] = Field(default_factory=list)
    outcome: str = ""
    why_matched: str = ""


class CompanyLead(BaseModel):
    lead_id: str
    name: str
    website: str = "not_found"
    domain: str = "unknown"
    industry: str = "unknown"
    country: str = "unknown"
    city: str = "unknown"
    company_size: str = "unknown"
    funding_stage: str = "unknown"
    funding_amount: str = "unknown"
    funding_date: str = "unknown"
    service_line_fit: ServiceLine = "exec_search"
    signal: Signal = Field(default_factory=Signal)
    contact: Contact = Field(default_factory=Contact)
    contacts: list[ContactCandidate] = Field(default_factory=list)
    score: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    proofs: list[ProofMatch] = Field(default_factory=list)
    email_draft: str = ""
    linkedin_note: str = ""
    qa_flags: list[str] = Field(default_factory=list)
    review_status: str = "pending"
    outreach_status: str = "not_sent"
    field_uncertainty: list[str] = Field(default_factory=list)
    discovery_queries: list[str] = Field(default_factory=list)
    query_id: str = ""
    discovery_web_query: str = ""
    why_interested: str = ""
    fetch_run_id: str = ""
    linked_at: str = ""


class ExtractedOrg(BaseModel):
    name: str
    website: str | None = None
    industry: str | None = None
    country: str | None = None
    city: str | None = None
    stage: str | None = None
    evidence_quote: str = ""
    signal_summary: str | None = None
    signal_type: SignalType = "other"
    signal_date: str | None = None
    is_relevant_to_icp: bool = False
    relevance_reason: str = ""
    discovery_web_query: str = ""
    source_url: str = ""


class ExtractBatch(BaseModel):
    companies: list[ExtractedOrg] = Field(default_factory=list)


class ParsedICP(BaseModel):
    geo: str = "India"
    cities: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)
    recency_days: int = 90
    company_types: list[str] = Field(default_factory=list)
    buying_signals: list[str] = Field(default_factory=list)
    notes: str = ""


class QuerySet(BaseModel):
    queries: list[str] = Field(default_factory=list)


class EnrichmentExtract(BaseModel):
    website: str | None = None
    industry: str | None = None
    country: str | None = None
    city: str | None = None
    stage: str | None = None
    funding_amount: str | None = None
    funding_date: str | None = None
    signal_type: SignalType = "other"
    signal_summary: str = ""
    signal_date: str | None = None
    evidence_quote: str = ""
    contact_name: str | None = None
    contact_role: str | None = None
    contact_why: str | None = None
    contact_quote: str | None = None
    inferred_fields: list[str] = Field(default_factory=list)


class ExtractedContact(BaseModel):
    name: str
    role: str = "unknown"
    why_relevant: str = ""
    evidence_quote: str = ""
    source_url: str = ""
    inferred: bool = False
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    twitter_url: str | None = None
    other_social: list[str] = Field(default_factory=list)


class ContactExtractBatch(BaseModel):
    contacts: list[ExtractedContact] = Field(default_factory=list)
