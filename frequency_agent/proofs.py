"""Tag-based Frequency proof-point matching. LLM does not pick from the full deck."""

from __future__ import annotations

from .llm import load_json
from .schemas import CompanyLead, ProofMatch


def load_proofs() -> list[dict]:
    data = load_json("proof_points.json")
    return list(data)


def _tokens(lead: CompanyLead, icp: dict) -> set[str]:
    parts = [
        lead.industry,
        lead.funding_stage,
        lead.signal.type,
        lead.signal.summary,
        lead.contact.role,
        " ".join(icp.get("sectors") or []),
        " ".join(icp.get("stages") or []),
        icp.get("service_line") or "",
        icp.get("geo") or "",
    ]
    blob = " ".join(p or "" for p in parts).lower()
    aliases = {
        "fintech": ["fintech", "bank", "lending", "payments", "wealth", "insur", "nbfc", "credit"],
        "ai": ["ai", "ml", "machine learning", "llm", "data science"],
        "saas": ["saas", "software"],
        "gtm": ["sales", "marketing", "cmo", "cro", "growth", "demand"],
        "finance": ["cfo", "finance", "controller", "treasury"],
        "tech": ["cto", "engineering", "sde", "devops"],
        "hr": ["chro", "talent", "hr"],
        "product": ["cpo", "product"],
        "deep_tech": ["deep tech", "semiconductor", "soc", "infra"],
        "consumer": ["d2c", "consumer", "retail", "brand", "ecommerce"],
        "series_a": ["series a"],
        "series_b": ["series b"],
        "series_c": ["series c"],
        "gcc": ["gcc", "captive", "global capability"],
        "india": ["india", "bengaluru", "bangalore", "hyderabad"],
    }
    found = set()
    for tag, keys in aliases.items():
        if any(k in blob for k in keys):
            found.add(tag)
    return found


def match_proofs(lead: CompanyLead, icp: dict, k: int = 3) -> list[ProofMatch]:
    service_line = icp.get("service_line") or "exec_search"
    tokens = _tokens(lead, icp)
    ranked: list[tuple[int, dict, list[str]]] = []
    for proof in load_proofs():
        if not proof.get("usable_in_outreach"):
            continue
        tags = set(proof.get("relevance_tags") or [])
        overlap = sorted(tokens & tags)
        score = len(overlap)
        if service_line in (proof.get("service_lines") or []):
            score += 1
        functions = set(proof.get("functions") or [])
        if tokens & functions:
            score += 2
            overlap = sorted(set(overlap) | (tokens & functions))
        if score <= 0:
            continue
        ranked.append((score, proof, overlap))
    ranked.sort(key=lambda x: x[0], reverse=True)
    chosen = ranked[:k]
    if not chosen:
        # Honest fallback: still pick the two closest exec-search proofs by industry blob
        fallback = [p for p in load_proofs() if "exec_search" in (p.get("service_lines") or [])][:2]
        return [
            ProofMatch(
                id=p["id"],
                company=p["company"],
                roles_placed=p.get("roles_placed") or [],
                outcome=p.get("outcome") or "",
                why_matched="Weak tag overlap — used as a modest adjacent proof, not a claimed analogue.",
            )
            for p in fallback
        ]
    return [
        ProofMatch(
            id=p["id"],
            company=p["company"],
            roles_placed=p.get("roles_placed") or [],
            outcome=p.get("outcome") or "",
            why_matched=f"Matched on {', '.join(overlap) or 'service-line adjacency'}.",
        )
        for _, p, overlap in chosen
    ]
