from __future__ import annotations

from frequency_agent.outreach import (
    _linkedin_fallback_from_email,
    _split_blocks,
    attach_person_drafts,
)
from frequency_agent.schemas import CompanyLead, ContactCandidate, Signal, Source


class _FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    def text(self, messages, temperature=0.5):  # noqa: ANN001
        self.calls += 1
        # Pull recipient line from the user message so each person gets a distinct draft
        user = messages[-1]["content"]
        name = "Contact"
        if "Recipient (direct):" in user:
            name = user.split("Recipient (direct):", 1)[1].split("\n", 1)[0].strip().split(",")[0]
        return (
            f"EMAIL:\nHi {name}, ExamplePay closed a Series B. "
            f"Frequency placed leaders at Savart. Open to 15 minutes?\n\n"
            f"LINKEDIN:\nHi {name} — saw the Series B. Happy to compare notes."
        )


def _lead_with_people() -> CompanyLead:
    people = [
        ContactCandidate(
            name="Jane Founder",
            role="CEO",
            is_primary=True,
            person_verified=True,
            rank=1,
            usable_in_outreach=True,
        ),
        ContactCandidate(
            name="Raj Ops",
            role="COO",
            is_primary=False,
            person_verified=True,
            rank=2,
            usable_in_outreach=True,
        ),
        ContactCandidate(
            name="Priya Growth",
            role="CGO",
            is_primary=False,
            person_verified=True,
            rank=3,
            usable_in_outreach=True,
        ),
    ]
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
        contact=people[0],
        contacts=list(people),
        verified_contacts=list(people),
    )


def test_split_blocks_email_and_linkedin():
    email, li = _split_blocks("EMAIL:\nHello mail\n\nLINKEDIN:\nHello LI")
    assert "Hello mail" in email
    assert "Hello LI" in li


def test_linkedin_fallback_not_empty():
    note = _linkedin_fallback_from_email("Hi Jane,\n\nSaw the raise. Worth a chat?\n\nBest,")
    assert "Hi Jane" in note
    assert note.strip()


def test_attach_person_drafts_for_every_contact():
    llm = _FakeLLM()
    lead = attach_person_drafts(llm, _lead_with_people(), {"raw_text": "fintech CEOs", "service_line": "exec_search"})
    assert len(lead.contacts) == 3
    assert len(lead.verified_contacts) == 3
    assert llm.calls == 3
    for person in lead.contacts:
        assert (person.email_draft or "").strip(), person.name
        assert (person.linkedin_note or "").strip(), person.name
        assert person.name.split()[0] in person.email_draft
        assert person.name.split()[0] in person.linkedin_note
    assert (lead.email_draft or "").strip()
    assert (lead.linkedin_note or "").strip()


def test_attach_fills_missing_linkedin_block(monkeypatch):
    class MissingLiLLM:
        def text(self, messages, temperature=0.5):  # noqa: ANN001
            return "EMAIL:\nHi only email body with Savart proof. 15 minutes?"

    lead = attach_person_drafts(
        MissingLiLLM(),
        _lead_with_people(),
        {"raw_text": "fintech", "service_line": "exec_search"},
    )
    for person in lead.contacts:
        assert (person.email_draft or "").strip()
        assert (person.linkedin_note or "").strip()
