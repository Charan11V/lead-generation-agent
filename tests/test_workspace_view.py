from frequency_agent.workspace_view import fetch_more_guard, merge_run_payloads


def test_merge_run_payloads_dedupes_and_keeps_first():
    runs = [
        {
            "run_id": "run-new",
            "query_id": "q1",
            "icp": "fintech CEOs",
            "service_line": "exec_search",
            "funnel": {"queued": 2},
            "logs": ["a"],
            "queries": ["q-a"],
            "leads": [
                {"lead_id": "L1", "name": "Alpha", "email_draft": "new draft"},
                {"lead_id": "L2", "name": "Beta"},
            ],
        },
        {
            "run_id": "run-old",
            "query_id": "q1",
            "funnel": {"queued": 3},
            "logs": ["b"],
            "queries": ["q-a", "q-b"],
            "leads": [
                {"lead_id": "L1", "name": "Alpha", "email_draft": "old draft"},
                {"lead_id": "L3", "name": "Gamma"},
            ],
        },
    ]
    merged = merge_run_payloads(runs)
    assert merged["run_ids"] == ["run-new", "run-old"]
    assert merged["query_id"] == "q1"
    assert merged["query_ids"] == ["q1"]
    assert [x["lead_id"] for x in merged["leads"]] == ["L1", "L2", "L3"]
    assert merged["leads"][0]["email_draft"] == "new draft"
    assert merged["funnel"]["queued"] == 5
    assert merged["logs"] == ["a", "b"]
    assert merged["queries"] == ["q-a", "q-b"]
    assert "2 fetches" in merged["label"]


def test_merge_mixed_query_ids_blocks_shared_query():
    merged = merge_run_payloads(
        [
            {"run_id": "r1", "query_id": "qa", "leads": [{"lead_id": "a", "name": "A"}]},
            {"run_id": "r2", "query_id": "qb", "leads": [{"lead_id": "b", "name": "B"}]},
        ]
    )
    assert merged["query_id"] == ""
    assert merged["query_ids"] == ["qa", "qb"]
    assert len(merged["leads"]) == 2


def test_fetch_more_guard_mixed_searches():
    ok, reason = fetch_more_guard(
        active_query_id="qa",
        locked_brief="fintech",
        query_ids_in_view=["qa", "qb"],
    )
    assert not ok
    assert "single search" in reason.lower()


def test_fetch_more_guard_same_search_multi_fetch():
    ok, reason = fetch_more_guard(
        active_query_id="qa",
        locked_brief="fintech",
        query_ids_in_view=["qa", "qa"],
    )
    assert ok
    assert reason == ""


def test_fetch_more_guard_missing_brief():
    ok, reason = fetch_more_guard(
        active_query_id="qa",
        locked_brief="",
        query_ids_in_view=["qa"],
    )
    assert not ok
    assert "Open or create" in reason
