"""Enrich continues after a single cluster failure."""

from __future__ import annotations

from frequency_agent import graph as graph_mod
from frequency_agent.schemas import ICP


def test_enrich_continues_after_one_cluster_failure(monkeypatch, tmp_path):
    clusters = [
        {"name": "GoodCo", "domain": "good.co", "mentions": [], "discovery_web_query": "q"},
        {"name": "BadCo", "domain": "bad.co", "mentions": [], "discovery_web_query": "q"},
        {"name": "AlsoGood", "domain": "also.good", "mentions": [], "discovery_web_query": "q"},
    ]
    icp = ICP(raw_text="fintech India Series B", service_line="exec_search", sectors=["fintech"])

    def fake_enrich(cluster, **kwargs):
        name = cluster["name"]
        if name == "BadCo":
            raise RuntimeError("simulated enrich boom")
        return (
            {
                "lead_id": f"id-{name.lower()}",
                "name": name,
                "domain": cluster.get("domain") or "unknown",
                "score": {"total": 55},
                "signal": {"usable_in_outreach": True, "type": "funding", "confidence": "HIGH"},
                "result_section": "unresolved",
                "discovery_web_query": "",
            },
            0,
        )

    class _Mem:
        def upsert_lead(self, *a, **k):
            return None

        def link_lead_to_query(self, *a, **k):
            return None

        def touch_query_session(self, *a, **k):
            return None

        def save_run(self, *a, **k):
            return None

    monkeypatch.setattr(graph_mod, "_enrich_cluster", fake_enrich)
    monkeypatch.setattr(graph_mod, "_llm", lambda state: object())
    monkeypatch.setattr(graph_mod, "_search", lambda state: object())
    monkeypatch.setattr(graph_mod, "_memory", lambda state=None: _Mem())
    monkeypatch.setattr(graph_mod, "meets_criteria", lambda lead: True)
    monkeypatch.setattr(
        graph_mod,
        "write_search_csv",
        lambda *a, **k: tmp_path / "out.csv",
    )
    monkeypatch.setenv("ENRICH_WORKERS", "1")
    monkeypatch.setenv("MAX_DISCOVER", "40")

    (tmp_path / "out.csv").write_text("ok", encoding="utf-8")

    state = {
        "openai_key": "sk-test",
        "icp": icp.model_dump(),
        "icp_hash": "abc",
        "seen_domains": [],
        "seen_names": [],
        "extracted": clusters,
        "queries": ["q"],
        "query_id": "qid-1",
        "run_id": "run-1",
        "logs": [],
        "funnel": {"skipped_this_run": 0},
    }
    out = graph_mod.enrich(state)
    names = {l["name"] for l in out["leads"]}
    assert "GoodCo" in names
    assert "AlsoGood" in names
    assert "BadCo" not in names
    assert out["funnel"].get("enrich_errors") == 1
    assert any("Enrich skipped" in line for line in out["logs"])
    assert any("BadCo" in line for line in out["logs"])


def test_map_parallel_return_exceptions():
    from frequency_agent.parallel import map_parallel

    def boom(x):
        if x == 2:
            raise ValueError("nope")
        return x * 10

    out = map_parallel([1, 2, 3], boom, max_workers=3, return_exceptions=True)
    assert out[0] == 10
    assert isinstance(out[1], ValueError)
    assert out[2] == 30
