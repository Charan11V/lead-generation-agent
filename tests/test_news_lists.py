"""Tests for curated Signal Desk news lists."""

from __future__ import annotations

from pathlib import Path

from frequency_agent.news_lists import NewsListStore
from frequency_agent.news_store import NewsStore


def _seed_news(db: Path, owner: str, *, n: int = 2) -> list[str]:
    store = NewsStore(db, owner_email=owner)
    rows = []
    for i in range(n):
        rows.append(
            {
                "fingerprint": f"fp-{owner}-{i}",
                "url": f"https://example.com/{owner}/{i}",
                "title": f"Story {i} for {owner}",
                "source": "Example",
                "provider": "test",
                "published_at": "2026-09-16T10:00:00+00:00",
                "snippet": "snippet",
                "why_relevant": "",
                "service_line": "exec_search",
                "score": 50 + i,
                "reasons": ["funding"],
            }
        )
    added = store.upsert_new(rows)
    return [a["news_id"] for a in added]


def test_create_rename_delete_list(tmp_path: Path):
    db = tmp_path / "lists.db"
    store = NewsListStore(db, owner_email="alice@example.com")
    created = store.create_list("Series B watch", "India fintech raises")
    assert created["list_id"].startswith("nli_")
    assert created["name"] == "Series B watch"
    assert created["description"] == "India fintech raises"
    assert created["item_count"] == 0

    lists = store.list_lists()
    assert len(lists) == 1
    assert lists[0]["list_id"] == created["list_id"]

    updated = store.update_list(
        created["list_id"],
        name="Series B + CXO",
        description="Raises and appointments",
    )
    assert updated is not None
    assert updated["name"] == "Series B + CXO"
    assert updated["description"] == "Raises and appointments"

    assert store.soft_delete_list(created["list_id"]) is True
    assert store.list_lists() == []
    assert store.get_list(created["list_id"]) is None


def test_add_and_remove_items(tmp_path: Path):
    db = tmp_path / "lists.db"
    owner = "alice@example.com"
    ids = _seed_news(db, owner, n=3)
    store = NewsListStore(db, owner_email=owner)
    lst = store.create_list("Desk picks")
    lid = lst["list_id"]

    n = store.add_items(lid, ids[:2])
    assert n == 2
    assert store.add_items(lid, [ids[0]]) == 0  # duplicate
    assert int(store.get_list(lid)["item_count"]) == 2

    items = store.list_items_with_news(lid)
    assert len(items) == 2
    assert {i["news_id"] for i in items} == set(ids[:2])
    assert all(i.get("title") for i in items)

    assert store.remove_items(lid, [ids[0]]) == 1
    assert int(store.get_list(lid)["item_count"]) == 1
    assert store.list_item_ids(lid) == [ids[1]]


def test_lists_are_owner_scoped(tmp_path: Path):
    db = tmp_path / "lists.db"
    alice_ids = _seed_news(db, "alice@example.com", n=1)
    bob_ids = _seed_news(db, "bob@example.com", n=1)
    alice = NewsListStore(db, owner_email="alice@example.com")
    bob = NewsListStore(db, owner_email="bob@example.com")
    a_list = alice.create_list("Alice list")
    b_list = bob.create_list("Bob list")
    assert alice.add_items(a_list["list_id"], alice_ids) == 1
    assert bob.add_items(b_list["list_id"], bob_ids) == 1
    # Bob cannot see or mutate Alice's list
    assert bob.get_list(a_list["list_id"]) is None
    assert bob.add_items(a_list["list_id"], bob_ids) == 0
    assert len(alice.list_lists()) == 1
    assert len(bob.list_lists()) == 1
    assert alice.list_lists()[0]["name"] == "Alice list"


def test_lists_containing_news(tmp_path: Path):
    db = tmp_path / "lists.db"
    owner = "alice@example.com"
    ids = _seed_news(db, owner, n=3)
    store = NewsListStore(db, owner_email=owner)
    watch = store.create_list("Watch")
    later = store.create_list("Later")
    store.add_items(watch["list_id"], [ids[0], ids[1]])
    store.add_items(later["list_id"], [ids[0]])

    mapping = store.lists_containing_news(ids)
    assert [x["name"] for x in mapping[ids[0]]] == ["Later", "Watch"]
    assert [x["name"] for x in mapping[ids[1]]] == ["Watch"]
    assert mapping[ids[2]] == []

    store.soft_delete_list(later["list_id"])
    mapping2 = store.lists_containing_news([ids[0]])
    assert [x["name"] for x in mapping2[ids[0]]] == ["Watch"]
