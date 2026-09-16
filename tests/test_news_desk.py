from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import sys
import threading
import time

from frequency_agent.memory import Memory
from frequency_agent.news_desk import run_signal_scan
from frequency_agent.news_relevance import (
    canonicalize_url,
    has_frequency_trigger,
    news_fingerprint,
    score_article,
)
from frequency_agent.news_sources import (
    _parse_rss,
    _unwrap_google_url,
    fetch_rss_feeds,
    in_window,
    parse_when,
)
from frequency_agent.news_store import NewsStore
from frequency_agent.news_ui import desk_hero_html, news_card_html
from frequency_agent.ui import inject


def test_funding_story_is_relevant():
    item = score_article(
        url="https://inc42.com/buzz/acme-raises-series-b/",
        title="Acme raises $40 million Series B in Bengaluru",
        snippet="The fintech startup will use the funds to hire a CFO and expand in India.",
        source="Inc42",
    )
    assert item.keep
    assert item.score >= 18
    assert item.service_line in {"exec_search", "capital_advisory"}
    from frequency_agent.news_relevance import deterministic_eval
    verdict = deterministic_eval(item)
    assert verdict["relevant"] is True
    assert "Frequency" in verdict["why"]


def test_cxo_departure_maps_to_exec_search():
    item = score_article(
        url="https://yourstory.com/2026/09/payco-cfo-resigns",
        title="PayCo CFO resigns as India fintech prepares next raise",
        snippet="The chief financial officer steps down after three years.",
    )
    assert item.keep
    assert item.service_line == "exec_search"


def test_fractional_story_maps_to_fractional_line():
    item = score_article(
        url="https://example.com/fractional-cfo-india",
        title="Why Indian SaaS firms are hiring a fractional CFO before Series A",
        snippet="Interim finance leadership is filling the gap until a full-time CXO is justified.",
    )
    assert item.keep
    assert item.service_line == "fractional_cxo"


def test_sports_and_listicles_are_dropped():
    sports = score_article(
        url="https://espn.com/cricket/ipl",
        title="IPL: Mumbai Indians win after late wicket",
        snippet="Match report from the cricket world cup warm-up.",
    )
    assert not sports.keep
    listing = score_article(
        url="https://blog.example.com/top-10-fintech-startups",
        title="Top 10 fintech startups to watch in India",
        snippet="A list of startups.",
    )
    assert not listing.keep


def test_weak_hits_are_kept_and_ranked_below_strong():
    weak = score_article(
        url="https://example.com/pune-store",
        title="Retail chain opens another store in Pune",
        snippet="A new outlet in the city.",
    )
    assert weak.keep
    assert weak.score < 18
    strong = score_article(
        url="https://inc42.com/series-b",
        title="Helio raises $25 million Series B in Bengaluru",
        snippet="The Indian SaaS startup will hire a CFO.",
    )
    assert strong.keep
    assert strong.score > weak.score


def test_canonicalize_strips_tracking_and_www():
    a = canonicalize_url("https://www.Inc42.com/buzz/story/?utm_source=twitter&utm_medium=cpc")
    b = canonicalize_url("https://inc42.com/buzz/story")
    assert a == b
    assert news_fingerprint(a) == news_fingerprint(b)


def test_rss_and_google_unwrap():
    xml = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>Acme raises Series B</title>
        <link>https://news.google.com/rss/articles/abc</link>
        <pubDate>Tue, 16 Sep 2026 01:00:00 GMT</pubDate>
        <description>&lt;a href="https://inc42.com/real-story"&gt;Acme raises Series B&lt;/a&gt;</description>
        <source>Inc42</source>
      </item>
    </channel></rss>
    """
    rows = _parse_rss(xml, provider="google_news")
    assert len(rows) == 1
    assert rows[0]["url"] == "https://inc42.com/real-story"
    assert "Acme" in rows[0]["title"]
    assert _unwrap_google_url("https://news.google.com/x", '<a href="https://foo.com/n">n</a>') == "https://foo.com/n"
    assert parse_when("20260916T010000Z").year == 2026
    stale = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    assert not in_window(stale, hours=36, provider="rss")
    assert in_window(fresh, hours=36, provider="rss")
    assert in_window("", hours=36, provider="google_news")
    assert not in_window("", hours=36, provider="rss")


def test_publisher_rss_keeps_frequency_hooks_only():
    assert has_frequency_trigger(
        "Helio raises $25 million Series B in Bengaluru",
        "The Indian SaaS startup will hire a CFO.",
    )
    assert has_frequency_trigger(
        "PayCo CFO resigns as fintech prepares next raise",
        "The chief financial officer steps down.",
    )
    assert has_frequency_trigger(
        "Nimbus announces acqui-hire of rival team",
        "The startup acquisition closed this week.",
    )
    assert not has_frequency_trigger(
        "Retail chain opens another store in Pune",
        "A new outlet in the city.",
    )
    assert not has_frequency_trigger(
        "Indian startups feel optimistic this year",
        "A roundup of the ecosystem.",
    )
    assert not has_frequency_trigger(
        "Sensex live: markets rally",
        "Stock tips for today and Nifty futures.",
    )
    assert has_frequency_trigger("Nimbus COO resigns after three years", "")
    assert has_frequency_trigger("Helio names a chief of staff", "")
    assert has_frequency_trigger("Acme starts a part-time CFO mandate", "")
    assert has_frequency_trigger("PayCo US market entry from Bengaluru", "")
    assert has_frequency_trigger("Founder flags a pre-IPO secondary", "")


def test_search_queries_cover_frequency_mandate():
    from frequency_agent.news_sources import (
        DDG_QUERIES,
        GDELT_QUERIES,
        GNEWS_QUERY,
        GOOGLE_QUERIES,
        GUARDIAN_QUERY,
        NEWSAPI_QUERY,
        NEWSDATA_QUERY,
    )

    blob = " ".join(
        GOOGLE_QUERIES
        + GDELT_QUERIES
        + DDG_QUERIES
        + (NEWSAPI_QUERY, GNEWS_QUERY, NEWSDATA_QUERY, GUARDIAN_QUERY)
    ).lower()
    for needle in (
        "series d",
        "chief of staff",
        "fractional",
        "venture debt",
        "gcc",
        "pre-ipo",
        "coo",
        "d2c",
        "acquisition",
        "head of talent",
        "part-time",
        "gic",
        "structured credit",
        "semiconductor",
        "executive search",
    ):
        assert needle in blob, needle


def test_fetch_rss_feeds_drops_off_brief_items(monkeypatch):
    from frequency_agent import news_sources as ns

    xml = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>Helio raises $25 million Series B in Bengaluru</title>
        <link>https://inc42.com/a-series-b</link>
        <description>The Indian SaaS startup will hire a CFO.</description>
        <pubDate>Tue, 16 Sep 2026 01:00:00 GMT</pubDate>
      </item>
      <item>
        <title>Sensex live market update</title>
        <link>https://moneycontrol.com/markets/sensex</link>
        <description>Nifty futures and stock tips for today.</description>
        <pubDate>Tue, 16 Sep 2026 01:00:00 GMT</pubDate>
      </item>
    </channel></rss>
    """

    class _Resp:
        status_code = 200
        text = xml

    monkeypatch.setattr(ns, "RSS_FEEDS", (("Inc42", "https://inc42.com/feed/"),))
    monkeypatch.setattr(ns, "_get", lambda client, url: _Resp())
    rows = fetch_rss_feeds(None)
    titles = [r["title"] for r in rows]
    assert titles == ["Helio raises $25 million Series B in Bengaluru"]


def _article(i: int, *, when: datetime | None = None) -> dict:
    stamp = (when or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return {
        "fingerprint": f"fp{i:04d}abcdefgh",
        "url": f"https://news.example.com/story-{i}",
        "title": f"Story {i} Series B funding in India",
        "source": "Inc42",
        "provider": "test",
        "published_at": stamp,
        "snippet": "fintech raise",
        "why_relevant": "Frequency exec search timing.",
        "service_line": "exec_search",
        "score": 40,
        "reasons": ["funding round"],
    }


def test_incremental_upsert_and_owner_isolation(tmp_path: Path):
    db = tmp_path / "news.db"
    a = NewsStore(db, owner_email="a@example.com")
    b = NewsStore(db, owner_email="b@example.com")
    first = a.upsert_new([_article(1), _article(2)])
    assert len(first) == 2
    again = a.upsert_new([_article(1), _article(2), _article(3)])
    assert len(again) == 1
    assert len(a.list_window(hours=24)) == 3
    assert b.list_window(hours=24) == []
    b.upsert_new([_article(9)])
    assert len(b.list_window(hours=24)) == 1
    assert {x["title"] for x in a.list_window(hours=24)} == {
        "Story 1 Series B funding in India",
        "Story 2 Series B funding in India",
        "Story 3 Series B funding in India",
    }


def test_user_soft_delete_admin_permanent(tmp_path: Path):
    db = tmp_path / "news-del.db"
    a = NewsStore(db, owner_email="a@example.com")
    b = NewsStore(db, owner_email="b@example.com")
    a.upsert_new([_article(1), _article(2)])
    b.upsert_new([_article(1)])
    ids_a = [r["news_id"] for r in a.list_window(hours=24)]
    a.soft_delete([ids_a[0]])
    assert len(a.list_window(hours=24)) == 1
    assert len(a.list_deleted()) == 1
    a.restore([ids_a[0]])
    assert len(a.list_window(hours=24)) == 2
    # Owner A cannot wipe B
    admin = NewsStore(db)
    b_id = b.list_window(hours=24)[0]["news_id"]
    assert a.permanently_delete([b_id]) == 0
    assert len(b.list_window(hours=24)) == 1
    assert admin.permanently_delete([b_id]) == 1
    assert b.list_window(hours=24) == []


def test_date_range_list_and_delete(tmp_path: Path):
    db = tmp_path / "news-range.db"
    store = NewsStore(db, owner_email="a@example.com")
    old = datetime.now(timezone.utc) - timedelta(days=5)
    new = datetime.now(timezone.utc) - timedelta(hours=2)
    store.upsert_new([_article(1, when=old), _article(2, when=new)])
    start = old - timedelta(hours=1)
    end = old + timedelta(hours=1)
    ranged = store.list_items(start=start, end=end)
    assert len(ranged) == 1
    assert "Story 1" in ranged[0]["title"]
    ids = store.ids_in_range(start, end)
    store.soft_delete(ids)
    assert len(store.list_items(start=start, end=end)) == 0
    assert len(store.list_window(hours=24)) == 1


def test_scan_is_incremental_within_24h(tmp_path: Path):
    db = tmp_path / "news-scan.db"
    raw1 = [
        {
            "url": "https://inc42.com/a-series-b",
            "title": "Helio raises $25 million Series B in Bengaluru",
            "snippet": "The Indian SaaS startup will hire a CFO.",
            "source": "Inc42",
            "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provider": "rss",
        }
    ]
    raw2 = raw1 + [
        {
            "url": "https://yourstory.com/cfo-resigns",
            "title": "Nimbus CFO resigns as fintech plans next round",
            "snippet": "Chief financial officer steps down in Mumbai.",
            "source": "YourStory",
            "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provider": "google_news",
        }
    ]
    with patch("frequency_agent.news_desk.harvest_news", return_value=(raw1, {"rss": 1})):
        first = run_signal_scan(owner_email="a@example.com", db_path=db)
    assert first["added"] == 1
    assert first["incremental"] is False
    with patch("frequency_agent.news_desk.harvest_news", return_value=(raw2, {"rss": 2})):
        second = run_signal_scan(owner_email="a@example.com", db_path=db)
    assert second["incremental"] is True
    assert second["added"] == 1
    assert second["visible"] == 2


def test_clear_workspace_wipes_news(tmp_path: Path):
    db = tmp_path / "wipe-news.db"
    mem_a = Memory(path=db, owner_email="a@example.com")
    mem_b = Memory(path=db, owner_email="b@example.com")
    a = NewsStore(db, owner_email="a@example.com")
    b = NewsStore(db, owner_email="b@example.com")
    a.upsert_new([_article(1)])
    b.upsert_new([_article(2)])
    mem_a.clear_all_data()
    assert a.list_window(hours=24) == []
    assert len(b.list_window(hours=24)) == 1
    mem_b.clear_all_data()
    assert b.list_window(hours=24) == []


def test_desk_html_is_escaped_and_themed():
    html = news_card_html(
        {
            "title": 'Acme <script>alert(1)</script> raises Series B',
            "url": "https://inc42.com/x",
            "source": "Inc42",
            "why_relevant": "Frequency should watch this.",
            "service_line": "exec_search",
            "score": 44,
            "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provider": "rss",
            "reasons": ["funding round"],
        }
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Exec search" in html
    assert "fx-desk-hero" in desk_hero_html()
    css = inject("dark")
    assert ".fx-news-card" in css
    assert ".fx-desk-hero" in css


def test_results_sorted_best_to_worst(tmp_path: Path):
    store = NewsStore(tmp_path / "rank.db", owner_email="a@example.com")
    low = _article(1)
    low["score"] = 6
    low["fingerprint"] = "fplow0000000001"
    mid = _article(2)
    mid["score"] = 22
    mid["fingerprint"] = "fpmid0000000002"
    high = _article(3)
    high["score"] = 48
    high["fingerprint"] = "fphi00000000003"
    store.upsert_new([low, high, mid])
    titles = [r["title"] for r in store.list_window(hours=24)]
    assert titles[0].startswith("Story 3")
    assert titles[1].startswith("Story 2")
    assert titles[2].startswith("Story 1")


def test_evaluation_persists_without_scan_llm(tmp_path: Path):
    from frequency_agent.news_desk import evaluate_article
    from unittest.mock import patch as _patch

    db = tmp_path / "eval.db"
    store = NewsStore(db, owner_email="a@example.com")
    store.upsert_new([_article(1)])
    nid = store.list_window(hours=24)[0]["news_id"]
    item = store.list_window(hours=24)[0]
    with _patch("frequency_agent.news_desk.LLM") as llm_cls:
        result = evaluate_article(item, openai_key="")
        llm_cls.assert_not_called()
    assert "why" in result
    assert store.save_evaluation(nid, relevant=result["relevant"], why=result["why"])
    loaded = store.list_window(hours=24)[0]
    assert loaded["eval_status"] in {"relevant", "not_relevant"}
    assert loaded["eval_why"]


def test_evaluate_article_openai_prompt_is_india_frequency():
    from frequency_agent.news_desk import evaluate_article, _ArticleEval

    captured: dict[str, str] = {}

    class _FakeLLM:
        extract_model = "gpt-test"

        def __init__(self, key: str) -> None:
            del key

        def parse(self, messages, schema, *, model=None, temperature=0.1):
            del schema, model, temperature
            captured["system"] = messages[0]["content"]
            captured["user"] = messages[1]["content"]
            return _ArticleEval(
                relevant=True,
                why="Named Bengaluru startup with a Series B — on-brief for Frequency in India.",
                service="exec_search",
            )

    item = {
        "title": "Helio raises $25 million Series B in Bengaluru",
        "snippet": "The Indian SaaS startup will hire a CFO.",
        "score": 40,
        "reasons": ["funding round"],
        "service_line": "exec_search",
    }
    with patch("frequency_agent.news_desk.LLM", _FakeLLM):
        result = evaluate_article(item, openai_key="sk-test")
    system = captured["system"].lower()
    user = captured["user"].lower()
    assert "operates in india" in system
    assert "executive search" in system
    assert "fractional" in system
    assert "capital advisory" in system
    assert "relevant=true" in system
    assert "only india" in system
    assert "answer only relevant or not" in system
    assert "us-only" in system
    assert "own knowledge" in system
    assert "when you are sure" in system
    assert "do not invent" in system
    assert "india only" in user
    assert "sure you know" in user
    assert result["relevant"] is True
    assert result["service_line"] == "exec_search"


def test_scan_does_not_call_openai(tmp_path: Path):
    raw = [
        {
            "url": "https://inc42.com/a-series-b",
            "title": "Helio raises $25 million Series B in Bengaluru",
            "snippet": "The Indian SaaS startup will hire a CFO.",
            "source": "Inc42",
            "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provider": "rss",
        }
    ]
    with patch("frequency_agent.news_desk.harvest_news", return_value=(raw, {"rss": 1})):
        with patch("frequency_agent.news_desk.LLM") as llm_cls:
            run_signal_scan(owner_email="a@example.com", db_path=tmp_path / "nollm.db")
            llm_cls.assert_not_called()


def test_check_relevance_starts_immediately_and_overlaps(tmp_path: Path):
    from frequency_agent import news_eval as eval_mod

    sys.modules.pop("_frequency_news_eval_runtime", None)
    db = tmp_path / "bg-eval.db"
    store = NewsStore(db, owner_email="a@example.com")
    store.upsert_new([_article(1), _article(2)])
    rows = store.list_window(hours=24)
    id1, id2 = rows[0]["news_id"], rows[1]["news_id"]

    entered = threading.Barrier(3)
    release = threading.Event()

    def slow_eval(item, openai_key=""):
        entered.wait(timeout=2)
        if not release.wait(timeout=2):
            raise TimeoutError("eval was not released")
        return {
            "relevant": True,
            "why": f"checked {item.get('news_id')}",
            "service_line": "exec_search",
        }

    with patch("frequency_agent.news_eval.evaluate_article", side_effect=slow_eval):
        t0 = time.monotonic()
        assert eval_mod.start_eval(news_id=id1, owner_email="a@example.com", db_path=db)
        assert eval_mod.start_eval(news_id=id2, owner_email="a@example.com", db_path=db)
        assert time.monotonic() - t0 < 0.5
        assert store.get_item(id1)["eval_status"] == "running"
        assert store.get_item(id2)["eval_status"] == "running"
        assert eval_mod.start_eval(news_id=id1, owner_email="a@example.com", db_path=db) is False
        entered.wait(timeout=2)
        release.set()

    deadline = time.monotonic() + 3
    while eval_mod.is_running(id1) or eval_mod.is_running(id2):
        if time.monotonic() > deadline:
            raise AssertionError("background evals did not finish")
        time.sleep(0.02)

    assert store.get_item(id1)["eval_status"] == "relevant"
    assert store.get_item(id2)["eval_status"] == "relevant"
    assert "checked" in store.get_item(id1)["eval_why"]


def test_stale_running_eval_is_reclaimed(tmp_path: Path):
    from frequency_agent import news_eval as eval_mod

    sys.modules.pop("_frequency_news_eval_runtime", None)
    db = tmp_path / "stale-eval.db"
    store = NewsStore(db, owner_email="a@example.com")
    store.upsert_new([_article(1)])
    nid = store.list_window(hours=24)[0]["news_id"]
    assert store.mark_eval_running(nid)
    assert store.get_item(nid)["eval_status"] == "running"
    assert eval_mod.reclaim_stale(store) == 1
    assert store.get_item(nid)["eval_status"] == ""
