from frequency_agent.memory import display_search_name


def test_legacy_auto_label_falls_back_to_icp():
    name = display_search_name(
        {"label": "exec_search · AI fintech Series B", "icp_text": "AI fintech Series B startups in India"}
    )
    assert name.startswith("AI fintech Series B")


def test_user_label_kept():
    assert display_search_name({"label": "My Fintech Push", "icp_text": "ignored brief"}) == "My Fintech Push"


def test_empty_label_uses_icp():
    assert "fintech" in display_search_name({"label": "", "icp_text": "fintech India"}).lower()
