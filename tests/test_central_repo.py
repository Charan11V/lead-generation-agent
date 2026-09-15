from frequency_agent.central_repo_ui import _apply_filters, _dup_keys, _enrich_light


def test_dup_keys_groups_shared_company_entity():
    rows = [
        {
            "id": 1,
            "owner_email": "a@x.com",
            "company": "Acme",
            "domain": "acme.com",
            "company_entity_id": "co_acme",
            "pipeline_status": "queued",
            "updated_at": "2026-09-01T10:00:00",
        },
        {
            "id": 2,
            "owner_email": "b@x.com",
            "company": "Acme Inc",
            "domain": "acme.com",
            "company_entity_id": "co_acme",
            "pipeline_status": "outreach_sent",
            "updated_at": "2026-09-02T10:00:00",
        },
        {
            "id": 3,
            "owner_email": "a@x.com",
            "company": "Other",
            "domain": "other.com",
            "company_entity_id": "co_other",
            "pipeline_status": "success",
            "updated_at": "2026-09-03T10:00:00",
        },
    ]
    light = [_enrich_light(r, profiles={}) for r in rows]
    assert _dup_keys(light) == {1, 2}
    open_only = _apply_filters(
        light,
        q="",
        owners=[],
        statuses=[],
        search_names=[],
        similar_only=False,
        open_only=True,
        date_from="",
        date_to="",
        focus_ids=set(),
        focus_only=False,
    )
    assert {r["id"] for r in open_only} == {1, 2}
