"""Tag-based Frequency proof-point matching. LLM does not pick from the full deck.

Scores company (lead) fit separately from ICP/search fit so every lead in a search
does not get the same proofs. Direct = company-aligned; related = search-adjacent
suggestion when there is no close company match.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from .branding import rewrite_frequency
from .llm import load_json
from .schemas import CompanyLead, ProofMatch

MatchTier = Literal["direct", "related"]

# Industry / domain tags: company must share these for a "direct" claim.
DOMAIN_TAGS = frozenset(
    {
        "fintech",
        "saas",
        "ai",
        "deep_tech",
        "consumer",
        "media",
        "life_science",
        "biotech",
        "lab",
        "analytics",
        "semiconductor",
        "hardware",
        "infra",
        "agri",
        "manufacturing",
        "sme",
    }
)

# Narrow industry families — shared broad tags (ai/saas) alone are not enough for "direct"
# when the company and proof sit in different strong families.
STRONG_DOMAIN_TAGS = frozenset(
    {
        "fintech",
        "consumer",
        "media",
        "life_science",
        "biotech",
        "lab",
        "analytics",
        "semiconductor",
        "hardware",
        "infra",
        "agri",
        "manufacturing",
        "deep_tech",
    }
)
BROAD_DOMAIN_TAGS = frozenset({"ai", "saas", "sme"})

# Families that can share "direct"/high rank without being identical industries.
COMPATIBLE_DOMAIN_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"analytics", "saas", "ai", "infra", "deep_tech", "data"}),
    frozenset({"fintech", "ai", "saas", "data"}),
    frozenset({"life_science", "biotech", "lab"}),
    frozenset({"agri", "manufacturing", "sme"}),
    frozenset({"semiconductor", "hardware", "deep_tech", "ai", "infra"}),
    frozenset({"consumer", "media"}),
)

# Stage / geo / company-type context — useful but not enough alone for "direct".
CONTEXT_TAGS = frozenset(
    {
        "india",
        "us",
        "series_a",
        "series_b",
        "series_c",
        "seed",
        "startup",
        "listed",
        "gcc",
        "growth",
    }
)

FUNCTION_TAGS = frozenset(
    {
        "gtm",
        "finance",
        "tech",
        "hr",
        "product",
        "ai",
        "growth",
        "brand",
        "cs",
        "operations",
        "data",
        "hardware",
    }
)

_ALIAS_MAP: dict[str, tuple[str, ...]] = {
    "fintech": (
        "fintech",
        "bank",
        "banking",
        "lending",
        "payments",
        "wealth",
        "insur",
        "insurance",
        "nbfc",
        "credit",
        "collections",
        "debt",
    ),
    "ai": ("ai", "ml", "machine learning", "llm", "generative ai", "genai"),
    "saas": ("saas", "software", "b2b software", "cloud software"),
    "analytics": (
        "analytics",
        "business intelligence",
        "bi platform",
        "data analytics",
        "search analytics",
        "thoughtspot",
    ),
    "gtm": ("sales", "marketing", "cmo", "cro", "growth", "demand gen", "demand"),
    "finance": ("cfo", "finance", "controller", "treasury", "portfolio management", "pms"),
    "tech": ("cto", "engineering", "sde", "devops", "software engineer"),
    "hr": ("chro", "talent", "hr ", " human resources", "avp hr"),
    "product": ("cpo", "product", "product manager", "product marketing"),
    "deep_tech": ("deep tech", "deeptech", "semiconductor", "soc", "mlsoc"),
    "consumer": ("d2c", "consumer", "retail", "brand", "ecommerce", "jewellery", "jewelry"),
    "series_a": ("series a", "series-a"),
    "series_b": ("series b", "series-b"),
    "series_c": ("series c", "series-c"),
    "seed": ("seed", "pre-seed", "preseed"),
    "gcc": ("gcc", "captive", "global capability"),
    "india": ("india", "bengaluru", "bangalore", "hyderabad", "mumbai", "delhi", "chennai", "pune"),
    "us": ("united states", " usa", "u.s.", "boston", "san francisco", "california", "seattle"),
    "life_science": (
        "life science",
        "life-science",
        "life sciences",
        "bioinformatics",
        "pharma",
        "pharmaceutical",
        "biopharma",
    ),
    "biotech": ("biotech", "biotechnology"),
    "lab": (
        "lab consumable",
        "lab supply",
        "lab supplies",
        "chromatography",
        "clinical diagnostic",
        "clinical diagnostics",
        "analytical chemistry",
        "labware",
    ),
    "agri": (
        "agri",
        "agriculture",
        "mushroom",
        "spawn",
        "farming",
        "horticulture",
        "food production",
    ),
    "manufacturing": ("manufacturing", "manufacturer", "industrial", "factory"),
    "media": ("media", "advertising", "adtech", "digital media"),
    "semiconductor": ("semiconductor", "chip", "asic", "fpga", "hardware design"),
    "hardware": ("hardware", "hw design", "device"),
    "infra": ("infra", "infrastructure", "ai infra", "cloud infra"),
    "data": ("data science", "data-science", "data platform", "fraud detection"),
    "sme": ("sme", "small business", "mid-market"),
    "startup": ("startup", "start-up", "early-stage"),
    "listed": ("listed", "public company", "ipo"),
    "growth": ("growth stage", "growth-stage", "late stage"),
}


@lru_cache(maxsize=1)
def load_proofs() -> tuple[dict, ...]:
    data = load_json("proof_points.json")
    rewritten = json.loads(rewrite_frequency(json.dumps(data)))
    return tuple(rewritten)


def _tokens_from_text(blob: str) -> set[str]:
    blob = (blob or "").lower()
    if not blob.strip():
        return set()
    found: set[str] = set()
    for tag, keys in _ALIAS_MAP.items():
        if any(k in blob for k in keys):
            found.add(tag)
    return found


def _lead_blob(lead: CompanyLead) -> str:
    people_roles = []
    for p in lead.contacts or []:
        role = getattr(p, "role", None) or (p.get("role") if isinstance(p, dict) else "") or ""
        if role:
            people_roles.append(str(role))
    return " ".join(
        [
            lead.name or "",
            lead.industry or "",
            lead.funding_stage or "",
            lead.company_size or "",
            lead.country or "",
            lead.city or "",
            lead.signal.type or "",
            lead.signal.summary or "",
            lead.contact.role or "",
            " ".join(people_roles),
            lead.why_interested or "",
        ]
    )


def _icp_blob(icp: dict) -> str:
    return " ".join(
        [
            " ".join(icp.get("sectors") or []),
            " ".join(icp.get("stages") or []),
            icp.get("service_line") or "",
            icp.get("geo") or "",
            icp.get("raw_text") or "",
        ]
    )


def _proof_tags(proof: dict) -> set[str]:
    tags = set(proof.get("relevance_tags") or [])
    tags.update(proof.get("functions") or [])
    industry = (proof.get("industry") or "").strip().lower().replace(" ", "_")
    if industry:
        tags.add(industry)
        # life_science_saas → life_science + saas
        for part in industry.split("_"):
            if part in DOMAIN_TAGS or part in _ALIAS_MAP:
                tags.add(part)
        if "life" in industry and "science" in industry:
            tags.add("life_science")
        if "ai" in industry:
            tags.add("ai")
    stage = (proof.get("stage") or "").strip().lower().replace(" ", "_")
    if stage:
        tags.add(stage)
    return tags


def _usage_hint(proof: dict, *, tier: MatchTier, lead: CompanyLead, overlap: list[str]) -> str:
    if tier == "direct":
        return ""
    company = proof.get("company") or "this proof"
    roles = ", ".join((proof.get("roles_placed") or [])[:2]) or "leadership roles"
    lead_ind = (lead.industry or "this sector").strip() or "this sector"
    proof_ind = (proof.get("industry") or "relevant").replace("_", " ")
    bits = [t for t in overlap if t][:4]
    via = f" (shared: {', '.join(bits)})" if bits else ""
    return (
        f"Not a direct match for {lead.name} ({lead_ind}). "
        f"Suggestion: cite {company} as an adjacent {proof_ind} example"
        f"{via} — e.g. similar function ({roles}) or search theme — without claiming "
        f"{lead.name} is the same kind of company."
    )


def _domains_compatible(lead_domain: set[str], proof_domain: set[str]) -> bool:
    if lead_domain & proof_domain & STRONG_DOMAIN_TAGS:
        return True
    lead_strong = lead_domain & STRONG_DOMAIN_TAGS
    proof_strong = proof_domain & STRONG_DOMAIN_TAGS
    if not lead_strong or not proof_strong:
        return True
    for group in COMPATIBLE_DOMAIN_GROUPS:
        if (lead_strong & group) and (proof_strong & group):
            return True
    # Also allow broad AI/SaaS bridges when both sides touch the same compatibility group via broad tags
    combined_lead = lead_domain
    combined_proof = proof_domain
    for group in COMPATIBLE_DOMAIN_GROUPS:
        if (combined_lead & group) and (combined_proof & group) and (lead_strong & group or not lead_strong):
            if proof_strong & group or not proof_strong:
                return True
    return False


def _is_direct_company_fit(
    *,
    lead_domain: set[str],
    proof_domain: set[str],
    lead_overlap: set[str],
) -> bool:
    strong_hit = lead_domain & proof_domain & STRONG_DOMAIN_TAGS
    if strong_hit:
        return True
    lead_strong = lead_domain & STRONG_DOMAIN_TAGS
    proof_strong = proof_domain & STRONG_DOMAIN_TAGS
    if lead_strong and proof_strong and not _domains_compatible(lead_domain, proof_domain):
        return False
    # Compatible families (e.g. lab/biotech ↔ life science, analytics ↔ AI infra)
    if lead_strong and proof_strong and _domains_compatible(lead_domain, proof_domain):
        return True
    broad_hit = lead_domain & proof_domain & BROAD_DOMAIN_TAGS
    if not broad_hit:
        return False
    if lead_strong or proof_strong:
        return bool(lead_overlap & (FUNCTION_TAGS | CONTEXT_TAGS | BROAD_DOMAIN_TAGS))
    return True


def _tier_and_why(
    *,
    lead_overlap: set[str],
    icp_overlap: set[str],
    lead_domain: set[str],
    proof_domain: set[str],
    service_hit: bool,
) -> tuple[MatchTier, str]:
    domain_hit = sorted(lead_domain & proof_domain)
    lead_fn = sorted(lead_overlap & FUNCTION_TAGS)
    lead_ctx = sorted(lead_overlap & CONTEXT_TAGS)
    search_bits = sorted(icp_overlap)

    if _is_direct_company_fit(
        lead_domain=lead_domain,
        proof_domain=proof_domain,
        lead_overlap=lead_overlap,
    ):
        parts = []
        strong = sorted((lead_domain & proof_domain) & STRONG_DOMAIN_TAGS)
        broad = sorted((lead_domain & proof_domain) & BROAD_DOMAIN_TAGS)
        if strong:
            parts.append(f"company industry: {', '.join(strong)}")
        elif broad:
            parts.append(f"company theme: {', '.join(broad)}")
        elif domain_hit:
            parts.append(f"company fit: {', '.join(domain_hit)}")
        if lead_fn:
            parts.append(f"function: {', '.join(lead_fn[:3])}")
        if lead_ctx:
            parts.append(f"context: {', '.join(lead_ctx[:2])}")
        if service_hit:
            parts.append("service-line match")
        return "direct", "Direct match — " + "; ".join(parts or ["company alignment"]) + "."

    reasons: list[str] = []
    if search_bits:
        reasons.append(f"search/ICP theme: {', '.join(search_bits[:4])}")
    if lead_fn:
        reasons.append(f"adjacent function: {', '.join(lead_fn[:3])}")
    if lead_ctx:
        reasons.append(f"shared context: {', '.join(lead_ctx[:2])}")
    if domain_hit:
        reasons.append(f"loose theme overlap only: {', '.join(domain_hit[:3])}")
    if service_hit and not reasons:
        reasons.append("same service line only")
    if not reasons:
        reasons.append("weak adjacency in the proof deck")
    return "related", "Related suggestion — " + "; ".join(reasons) + "."


def select_outreach_proofs(
    proofs: list[ProofMatch] | None,
    *,
    max_n: int = 2,
) -> list[ProofMatch]:
    """Proofs safe to put in outbound email/LinkedIn.

    Prefer direct company fits. If none, allow related search-adjacent proofs
    (caller must frame them as suggestions, not analogues).
    """
    items = list(proofs or [])
    if not items:
        return []
    direct = [p for p in items if (getattr(p, "match_tier", None) or "direct") == "direct"]
    related = [p for p in items if (getattr(p, "match_tier", None) or "") == "related"]
    if direct:
        return direct[:max_n]
    return related[:max_n]


def match_proofs(lead: CompanyLead, icp: dict, k: int = 3) -> list[ProofMatch]:
    service_line = (icp.get("service_line") or lead.service_line_fit or "exec_search").strip()
    lead_tokens = _tokens_from_text(_lead_blob(lead))
    icp_tokens = _tokens_from_text(_icp_blob(icp))
    # If the lead has almost no tags, lean a bit more on ICP so empty industries still get something.
    lead_thin = len(lead_tokens & DOMAIN_TAGS) == 0

    ranked: list[tuple[float, MatchTier, dict, list[str], str, str]] = []
    for proof in load_proofs():
        if not proof.get("usable_in_outreach"):
            continue
        tags = _proof_tags(proof)
        functions = set(proof.get("functions") or [])
        lead_overlap = lead_tokens & tags
        icp_overlap = icp_tokens & tags
        proof_domain = tags & DOMAIN_TAGS
        lead_domain = lead_tokens & DOMAIN_TAGS

        score = 0.0
        # Company-first scoring (prevents identical ICP-driven lists for every lead).
        strong_hit = lead_domain & (tags & STRONG_DOMAIN_TAGS)
        score += 6.0 * len(strong_hit)
        score += 4.0 * len(lead_overlap & DOMAIN_TAGS)
        score += 2.5 * len(lead_overlap & functions)
        score += 1.5 * len(lead_overlap & FUNCTION_TAGS)
        score += 1.0 * len(lead_overlap & CONTEXT_TAGS)
        # Search/ICP as secondary boost — relevant for the run, not a company claim.
        score += 1.2 * len(icp_overlap & DOMAIN_TAGS)
        score += 0.8 * len(icp_overlap & functions)
        score += 0.5 * len(icp_overlap & CONTEXT_TAGS)
        service_hit = service_line in (proof.get("service_lines") or [])
        if service_hit:
            score += 1.0
        if lead_thin:
            score += 0.8 * len(icp_overlap)

        lead_strong = lead_domain & STRONG_DOMAIN_TAGS
        proof_strong = tags & STRONG_DOMAIN_TAGS
        industry_conflict = bool(
            lead_strong
            and proof_strong
            and not _domains_compatible(lead_domain, tags & DOMAIN_TAGS)
        )
        if industry_conflict:
            # Keep search-themed proofs available, but below company-aligned ones.
            score *= 0.35
        elif strong_hit:
            score += 2.0

        if score <= 0:
            continue

        tier, why = _tier_and_why(
            lead_overlap=lead_overlap,
            icp_overlap=icp_overlap,
            lead_domain=lead_domain,
            proof_domain=proof_domain,
            service_hit=service_hit,
        )
        # Soft penalty: ICP-only related proofs rank below company-aligned ones.
        if tier == "related":
            score *= 0.72
        overlap_display = sorted((lead_overlap | icp_overlap) & tags)
        hint = _usage_hint(proof, tier=tier, lead=lead, overlap=overlap_display)
        ranked.append((score, tier, proof, overlap_display, why, hint))

    ranked.sort(key=lambda x: (0 if x[1] == "direct" else 1, -x[0]))

    chosen = ranked[:k]
    if not chosen:
        return _fallback_related(lead, service_line=service_line, k=min(2, k))

    # Prefer at least one related search-themed proof if we only have weak directs? Not needed.
    # If all are related, keep them; messaging already marks suggestions.
    return [_to_match(score, tier, proof, why, hint) for score, tier, proof, _, why, hint in chosen]


def _fallback_related(lead: CompanyLead, *, service_line: str, k: int) -> list[ProofMatch]:
    pool = [
        p
        for p in load_proofs()
        if p.get("usable_in_outreach") and service_line in (p.get("service_lines") or [])
    ]
    if not pool:
        pool = [p for p in load_proofs() if p.get("usable_in_outreach")]
    out: list[ProofMatch] = []
    for p in pool[:k]:
        why = (
            "Related suggestion — no close company or search tag overlap; "
            "use only as a modest adjacent example, not a claimed analogue."
        )
        hint = _usage_hint(p, tier="related", lead=lead, overlap=[])
        out.append(
            ProofMatch(
                id=p["id"],
                company=p["company"],
                roles_placed=list(p.get("roles_placed") or []),
                outcome=p.get("outcome") or "",
                why_matched=why,
                match_tier="related",
                usage_hint=hint,
            )
        )
    return out


def _to_match(
    _score: float,
    tier: MatchTier,
    proof: dict,
    why: str,
    hint: str,
) -> ProofMatch:
    return ProofMatch(
        id=proof["id"],
        company=proof["company"],
        roles_placed=list(proof.get("roles_placed") or []),
        outcome=proof.get("outcome") or "",
        why_matched=why,
        match_tier=tier,
        usage_hint=hint if tier == "related" else "",
    )
