from frequency_agent.schemas import (
    Contact,
    ContactChannel,
    ContactCandidate,
    CompanyLead,
    Signal,
    fresh_contact,
    fresh_contact_candidate,
    fresh_signal,
    to_dict,
)


def test_fresh_contact_revalidates_channels():
    ch = ContactChannel(kind="email", value="ceo@example.com", confidence="HIGH", priority=100)
    cand = ContactCandidate(
        name="Ada Lovelace",
        role="CEO",
        why="Named in source",
        usable_in_outreach=True,
        channels=[ch],
        email="ceo@example.com",
        relevance_score=40,
        rank=1,
        is_primary=True,
    )
    contact = fresh_contact(cand)
    assert isinstance(contact, Contact)
    assert contact.channels[0].value == "ceo@example.com"
    assert isinstance(contact.channels[0], ContactChannel)

    refreshed = fresh_contact_candidate(cand)
    assert refreshed.relevance_score == 40
    assert refreshed.channels[0].value == "ceo@example.com"


def test_signal_instance_into_company_lead_via_dump():
    """Mirrors _enrich_cluster: dump nested Signal so reload class splits can't fail."""
    signal = Signal(type="funding", summary="Raised Series B", confidence="HIGH")
    lead = CompanyLead(
        lead_id="lead-1",
        name="PayCo",
        signal=to_dict(signal) if hasattr(signal, "model_dump") else signal,
    )
    assert isinstance(lead.signal, Signal)
    assert lead.signal.type == "funding"
    assert fresh_signal(signal).summary == "Raised Series B"
