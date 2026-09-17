"""Tests for news-list deep research bookkeeping and tagging."""

from __future__ import annotations

from pathlib import Path

from frequency_agent.news_deep import (
    NEWS_EVENT_TAG,
    article_to_cluster,
    guess_company_from_title,
    is_junk_news_url,
    is_news_event_item,
    news_event_icp_text,
    news_event_search_name,
    sanitize_news_lead,
    unwrap_article_url,
)
from frequency_agent.news_lists import NewsListStore
from frequency_agent.news_store import NewsStore


def _seed(db: Path, owner: str, n: int = 2) -> list[str]:
    store = NewsStore(db, owner_email=owner)
    rows = [
        {
            "fingerprint": f"fp-deep-{owner}-{i}",
            "url": f"https://news.example/{i}",
            "title": f"Acme raises Series B {i}",
            "source": "Example",
            "provider": "test",
            "published_at": "2026-09-16T10:00:00+00:00",
            "snippet": "Acme Pay raised funding",
            "why_relevant": "",
            "service_line": "exec_search",
            "score": 70,
            "reasons": ["funding"],
        }
        for i in range(n)
    ]
    return [a["news_id"] for a in store.upsert_new(rows)]


def test_pending_and_save_deep_research(tmp_path: Path):
    db = tmp_path / "deep.db"
    owner = "alice@example.com"
    ids = _seed(db, owner, n=2)
    lists = NewsListStore(db, owner_email=owner)
    lst = lists.create_list("Watch")
    lid = lst["list_id"]
    lists.add_items(lid, ids)

    pending = lists.pending_deep_research_ids(lid)
    assert set(pending) == set(ids)

    fake_lead = {
        "lead_id": "lead_x",
        "name": "Acme Pay",
        "email_draft": "Hi",
        "linkedin_note": "Hi LI",
        "source_kind": "news_event",
        "queue_company_email": True,
    }
    assert lists.save_deep_research(lid, ids[0], fake_lead)
    pending2 = lists.pending_deep_research_ids(lid)
    assert pending2 == [ids[1]]

    items = lists.list_items_with_news(lid)
    enriched = [i for i in items if i.get("is_enriched")]
    assert len(enriched) == 1
    assert enriched[0]["lead"]["name"] == "Acme Pay"
    assert enriched[0]["news_id"] == ids[0]


def test_news_event_tag_helpers():
    name = news_event_search_name("My list", "Some title")
    assert name.startswith(NEWS_EVENT_TAG)
    assert "My list" in name
    text = news_event_icp_text(
        {"title": "Raise", "url": "https://x", "snippet": "funded"},
        list_name="My list",
    )
    assert NEWS_EVENT_TAG in text
    assert is_news_event_item({"search_name": name})
    assert is_news_event_item({"source_kind": "news_event"})
    assert not is_news_event_item({"search_name": "Normal ICP search"})


def test_guess_company_skips_llm_when_headline_clear():
    assert (
        guess_company_from_title(
            "Integrated aesthetic surgery platform TRUE ARTIS raises Rs 11.4 crore in seed funding"
        )
        == "TRUE ARTIS"
    )
    assert guess_company_from_title("Acme raises $10M Series A") == "Acme"


def test_junk_google_news_urls_stripped():
    gnews = (
        "https://news.google.com/rss/articles/CBMi5gFBVV95cUxNeWFyODNDR0pXbE4z?"
        "oc=5"
    )
    assert is_junk_news_url(gnews)
    assert not is_junk_news_url("https://indianstartupnews.com/true-artis-funding")

    payload = sanitize_news_lead(
        {
            "website": gnews,
            "domain": "news.google.com",
            "best_approach_channel": f"url:{gnews}",
            "approach_channels": [
                {"kind": "url", "label": "Company website", "value": gnews, "source_url": gnews},
                {
                    "kind": "email",
                    "label": "Founder",
                    "value": "founder@trueartis.com",
                    "source_url": "https://trueartis.com",
                },
            ],
            "signal": {
                "sources": [
                    {"url": gnews, "title": "wrapper"},
                    {"url": "https://indianstartupnews.com/x", "title": "real"},
                ]
            },
        }
    )
    assert payload["website"] == "not_found"
    assert payload["best_approach_channel"].startswith("email:")
    assert all(not is_junk_news_url(c["value"]) for c in payload["approach_channels"])
    assert all(not is_junk_news_url(s["url"]) for s in payload["signal"]["sources"])


def test_article_cluster_does_not_seed_google_news_as_website():
    gnews = "https://news.google.com/rss/articles/CBMi5gFBVV95?"
    cluster = article_to_cluster(
        {
            "title": "TRUE ARTIS raises seed funding",
            "url": gnews,
            "snippet": 'Story <a href="https://publisher.example/true-artis">here</a>',
            "published_at": "2026-09-16T00:00:00+00:00",
        },
        "TRUE ARTIS",
        list_name="Watch",
    )
    assert cluster["website"] == "not_found"
    assert cluster["mentions"]
    assert cluster["mentions"][0]["source_url"] == "https://publisher.example/true-artis"
    assert unwrap_article_url(gnews, cluster["mentions"][0]["evidence_quote"]).startswith(
        "https://publisher.example/"
    )
