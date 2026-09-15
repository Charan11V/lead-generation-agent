from frequency_agent.schemas import SearchHit
from frequency_agent.search import SearchClient, _tavily_key_id, reset_provider_circuit


class _BoomTavily:
    def search(self, **_kwargs):
        raise RuntimeError("This request exceeds your plan's set usage limit. Please upgrade your plan.")


def test_tavily_quota_falls_back_to_ddg(monkeypatch):
    reset_provider_circuit()
    client = SearchClient(tavily_key="tvly-test")
    client._tavily = _BoomTavily()

    fallback = [
        SearchHit(query="q", url="https://example.com/acme", title="Acme raises Series B", snippet="funding")
    ]
    monkeypatch.setattr(client, "_ddg_search", lambda query, max_results: fallback)

    out = client.search("fintech India Series B")
    assert len(out) == 1
    assert out[0].url == "https://example.com/acme"
    assert "usage limit" in (client.fallback_reason or "").lower() or "plan" in (client.fallback_reason or "").lower()
    assert client._tavily is None


def test_tavily_quota_circuit_skips_later_clients(monkeypatch):
    reset_provider_circuit()
    first = SearchClient(tavily_key="tvly-test")
    first._tavily = _BoomTavily()
    monkeypatch.setattr(first, "_ddg_search", lambda query, max_results: [])
    first.search("q1")

    second = SearchClient(tavily_key="tvly-test")
    assert second._tavily is None
    assert second.fallback_reason
    reset_provider_circuit()


def test_tavily_circuit_is_per_key(monkeypatch):
    """One user's exhausted key must not disable another user's Tavily key."""
    reset_provider_circuit()
    bad = SearchClient(tavily_key="tvly-user-a")
    bad._tavily = _BoomTavily()
    monkeypatch.setattr(bad, "_ddg_search", lambda query, max_results: [])
    bad.search("q1")

    other = SearchClient(tavily_key="tvly-user-b")
    # Different key — still allowed to construct a client (mock out real Tavily).
    assert other._key_id == _tavily_key_id("tvly-user-b")
    assert other._key_id != bad._key_id
    assert not other._this_key_disabled()
    reset_provider_circuit()
