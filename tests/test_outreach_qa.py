from frequency_agent.outreach import qa_outreach
from frequency_agent.schemas import CompanyLead, Contact, ProofMatch, Signal, Source


def _lead() -> CompanyLead:
    return CompanyLead(
        lead_id="x",
        name="ExamplePay",
        signal=Signal(
            type="funding",
            summary="ExamplePay closed a Series B round in Bengaluru",
            date="2026-08-01",
            confidence="HIGH",
            usable_in_outreach=True,
            evidence_quote="closed a Series B round",
            sources=[Source(url="https://inc42.com/x", snippet="closed a Series B round")],
        ),
        contact=Contact(name="Jane Founder", role="CEO", usable_in_outreach=True, confidence="HIGH"),
        proofs=[
            ProofMatch(id="savart", company="Savart", roles_placed=["CGO"], outcome="Users 250K to 2 million", why_matched="fintech"),
            ProofMatch(id="oro", company="Oro", roles_placed=["CMO"], outcome="Revenue to $15 million", why_matched="fintech"),
        ],
    )


def test_banned_greeting_is_flagged():
    email = (
        "I hope this email finds you well. Just wanted to reach out about ExamplePay "
        "and the Series B round in Bengaluru. Savart and Oro are relevant. "
        "We are a leading search firm. Let's book a demo?"
    )
    flags = qa_outreach(_lead(), email, "hi")
    assert any("Banned phrase" in f for f in flags)


def test_clean_draft_passes_core_gates():
    email = (
        "ExamplePay's Series B round in Bengaluru is a classic moment when the leadership bench has to catch up to the capital. "
        "Frequency recently placed a CGO at Savart who took the user base from 250K to 2 million, and a CMO at Oro as revenue moved to $15 million. "
        "If the search is live, 15 minutes is enough to compare notes."
    )
    linkedin = (
        "Saw the Series B note on ExamplePay. Frequency's Savart and Oro work is the closest analogue — happy to compare notes if useful."
    )
    flags = qa_outreach(_lead(), email, linkedin)
    serious = [f for f in flags if "Banned" in f or "does not cite" in f or "Unsourced number" in f]
    assert serious == []
