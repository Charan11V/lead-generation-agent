"""Company-level outreach selection, editing helpers, and queue bundles."""

from __future__ import annotations

import json
import re
from typing import Any

from .send_queue import subject_line

COMPANY_CHANNEL = "company"
BUNDLE_VERSION = 1


def _slug(text: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return (raw or "x")[:48]


def person_key(person: dict | None, *, fallback: str = "company") -> str:
    if not person:
        return fallback
    name = (person.get("name") or "").strip()
    role = (person.get("role") or "").strip()
    email = (person.get("email") or "").strip().lower()
    if email:
        return _slug(email)
    if name:
        return _slug(f"{name}-{role}" if role else name)
    return fallback


def _named_people(lead: dict) -> list[dict]:
    people = [
        p
        for p in (lead.get("verified_contacts") or lead.get("contacts") or [])
        if isinstance(p, dict)
        and (p.get("name") or "").lower() not in {"", "unknown", "not_found"}
    ]
    if people:
        return people[:6]
    contact = lead.get("contact") if isinstance(lead.get("contact"), dict) else {}
    if (contact.get("name") or "").lower() not in {"", "unknown", "not_found"}:
        return [contact]
    return []


def _draft_ok(text: str | None) -> bool:
    """Any non-empty draft can be queued if the user selects it, including blocked/unverified copy."""
    return bool((text or "").strip())


def _person_email_draft(lead: dict, person: dict) -> str:
    mail = (person.get("email_draft") or "").strip()
    if mail:
        return mail
    if person.get("is_primary"):
        return (lead.get("email_draft") or "").strip()
    return ""


def _person_linkedin_draft(lead: dict, person: dict) -> str:
    note = (person.get("linkedin_note") or "").strip()
    if note:
        return note
    if person.get("is_primary"):
        return (lead.get("linkedin_note") or "").strip()
    return ""


def list_message_targets(lead: dict) -> list[dict]:
    """Editable / selectable message slots for a company result."""
    targets: list[dict] = []
    people = _named_people(lead)
    lead_email = (lead.get("email_draft") or "").strip()
    lead_li = (lead.get("linkedin_note") or "").strip()
    primary = next((p for p in people if p.get("is_primary")), people[0] if people else None)
    for person in people:
        key = person_key(person)
        email_body = _person_email_draft(lead, person)
        li_body = _person_linkedin_draft(lead, person)
        if person is primary:
            if not email_body:
                email_body = lead_email
            if not li_body:
                li_body = lead_li
        targets.append(
            {
                "target_key": key,
                "scope": "person",
                "person": person,
                "label": person.get("name") or "Contact",
                "role": person.get("role") or "",
                "email_draft": email_body,
                "linkedin_note": li_body,
                "has_email": _draft_ok(email_body),
                "has_linkedin": _draft_ok(li_body),
                "select_email": bool(
                    person["queue_email"]
                    if "queue_email" in person
                    else False
                ),
                "select_linkedin": bool(
                    person["queue_linkedin"]
                    if "queue_linkedin" in person
                    else False
                ),
            }
        )
    if not people:
        targets.append(
            {
                "target_key": "company",
                "scope": "company",
                "person": None,
                "label": "Company channel",
                "role": lead.get("best_approach_channel") or "Indirect",
                "email_draft": lead_email,
                "linkedin_note": lead_li,
                "has_email": _draft_ok(lead_email),
                "has_linkedin": _draft_ok(lead_li),
                "select_email": bool(
                    lead["queue_company_email"]
                    if "queue_company_email" in lead
                    else False
                ),
                "select_linkedin": bool(
                    lead["queue_company_linkedin"]
                    if "queue_company_linkedin" in lead
                    else False
                ),
            }
        )
    return targets


def contacts_summary(lead: dict) -> list[dict]:
    out = []
    for person in _named_people(lead):
        out.append(
            {
                "name": person.get("name") or "",
                "role": person.get("role") or "",
                "email": person.get("email") or "",
                "phone": person.get("phone") or "",
                "linkedin_url": person.get("linkedin_url") or "",
            }
        )
    if out:
        return out
    for ch in (lead.get("approach_channels") or [])[:6]:
        if not isinstance(ch, dict):
            continue
        out.append(
            {
                "name": ch.get("label") or ch.get("kind") or "Channel",
                "role": ch.get("kind") or "",
                "email": ch.get("value") if (ch.get("kind") or "") == "email" else "",
                "phone": ch.get("value") if (ch.get("kind") or "") == "phone" else "",
                "linkedin_url": "",
            }
        )
    return out


def signal_summary(lead: dict) -> str:
    signal = lead.get("signal") if isinstance(lead.get("signal"), dict) else {}
    kind = (signal.get("type") or "").replace("_", " ").strip()
    text = (signal.get("summary") or "").strip()
    if kind and text:
        return f"{kind}: {text}"
    return text or kind or ""


def apply_target_edits(
    lead: dict,
    *,
    target_key: str,
    email_draft: str | None = None,
    linkedin_note: str | None = None,
    select_email: bool | None = None,
    select_linkedin: bool | None = None,
) -> dict:
    """Mutate lead drafts/selection for one person or company-level target."""
    people = _named_people(lead)
    if target_key == "company" or not people:
        if email_draft is not None:
            lead["email_draft"] = email_draft.strip()
        if linkedin_note is not None:
            lead["linkedin_note"] = linkedin_note.strip()
        if select_email is not None:
            lead["queue_company_email"] = bool(select_email)
        if select_linkedin is not None:
            lead["queue_company_linkedin"] = bool(select_linkedin)
        return lead

    for person in people:
        if person_key(person) != target_key:
            continue
        if email_draft is not None:
            person["email_draft"] = email_draft.strip()
            if person.get("is_primary"):
                lead["email_draft"] = email_draft.strip()
        if linkedin_note is not None:
            person["linkedin_note"] = linkedin_note.strip()
            if person.get("is_primary"):
                lead["linkedin_note"] = linkedin_note.strip()
        if select_email is not None:
            person["queue_email"] = bool(select_email)
        if select_linkedin is not None:
            person["queue_linkedin"] = bool(select_linkedin)
        # Keep list copies in sync when both contacts + verified_contacts exist.
        _sync_person_lists(lead, person)
        break
    return lead


def _sync_person_lists(lead: dict, person: dict) -> None:
    key = person_key(person)
    for field in ("contacts", "verified_contacts"):
        rows = lead.get(field)
        if not isinstance(rows, list):
            continue
        for i, row in enumerate(rows):
            if isinstance(row, dict) and person_key(row) == key:
                rows[i] = {**row, **person}
    contact = lead.get("contact")
    if isinstance(contact, dict) and person_key(contact) == key:
        lead["contact"] = {**contact, **person}


def selected_messages(lead: dict) -> list[dict]:
    messages: list[dict] = []
    for target in list_message_targets(lead):
        person = target.get("person") or {}
        base = {
            "target_key": target["target_key"],
            "scope": target["scope"],
            "person_name": target["label"],
            "person_role": target["role"],
            "email": (person.get("email") or "") if person else "",
            "phone": (person.get("phone") or "") if person else "",
            "linkedin_url": (person.get("linkedin_url") or "") if person else "",
        }
        if target.get("select_email") and target.get("has_email"):
            messages.append(
                {
                    **base,
                    "kind": "email",
                    "body": (target.get("email_draft") or "").strip(),
                }
            )
        if target.get("select_linkedin") and target.get("has_linkedin"):
            messages.append(
                {
                    **base,
                    "kind": "linkedin",
                    "body": (target.get("linkedin_note") or "").strip(),
                }
            )
    return messages


def can_enqueue_company(lead: dict) -> tuple[bool, str]:
    status = (lead.get("review_status") or "pending").lower()
    if status == "rejected":
        return False, "Rejected leads cannot enter the send queue."
    msgs = selected_messages(lead)
    if not msgs:
        return False, "Select at least one outreach message or LinkedIn note to queue."
    return True, ""


def _lead_snapshot_for_detail(lead: dict, messages: list[dict]) -> dict:
    """Full company result with only selected message bodies kept."""
    snap = json.loads(json.dumps(lead, default=str))
    selected_keys = {
        (m.get("target_key"), m.get("kind")) for m in messages if isinstance(m, dict)
    }
    people = _named_people(snap)
    if people:
        kept = []
        for person in people:
            key = person_key(person)
            email_on = (key, "email") in selected_keys
            li_on = (key, "linkedin") in selected_keys
            if not email_on and not li_on:
                # Keep contact identity for dossier, clear unselected drafts.
                person = dict(person)
                person["email_draft"] = ""
                person["linkedin_note"] = ""
                person["queue_email"] = False
                person["queue_linkedin"] = False
                kept.append(person)
                continue
            person = dict(person)
            if not email_on:
                person["email_draft"] = ""
            if not li_on:
                person["linkedin_note"] = ""
            person["queue_email"] = email_on
            person["queue_linkedin"] = li_on
            kept.append(person)
        snap["contacts"] = kept
        snap["verified_contacts"] = [
            p for p in kept if p.get("person_verified") or snap.get("result_section") == "verified_people"
        ] or kept
        primary = next((p for p in kept if p.get("is_primary")), kept[0] if kept else {})
        snap["contact"] = primary
        snap["email_draft"] = (primary.get("email_draft") or "") if (person_key(primary), "email") in selected_keys else ""
        snap["linkedin_note"] = (
            (primary.get("linkedin_note") or "")
            if (person_key(primary), "linkedin") in selected_keys
            else ""
        )
    else:
        if ("company", "email") not in selected_keys:
            snap["email_draft"] = ""
        if ("company", "linkedin") not in selected_keys:
            snap["linkedin_note"] = ""
    snap["_selected_messages"] = messages
    return snap


def company_queue_payload(
    lead: dict,
    *,
    search_name: str = "",
    icp_text: str = "",
) -> dict:
    search_name = (search_name or "").strip()
    icp_text = (icp_text or "").strip()
    if not search_name:
        search_name = search_label_for_lead(lead, search_name="", icp_text=icp_text)
    messages = selected_messages(lead)
    contacts = contacts_summary(lead)
    signal = lead.get("signal") if isinstance(lead.get("signal"), dict) else {}
    bundle = {
        "version": BUNDLE_VERSION,
        "kind": "company_bundle",
        "lead_id": lead.get("lead_id") or "",
        "company": lead.get("name") or "",
        "domain": lead.get("domain") or "",
        "search_name": search_name,
        "icp_text": icp_text,
        "signal": {
            "type": signal.get("type") or "",
            "summary": signal.get("summary") or "",
            "confidence": signal.get("confidence") or "",
            "usable_in_outreach": bool(signal.get("usable_in_outreach")),
        },
        "signal_text": signal_summary(lead),
        "contacts": contacts,
        "selected_messages": messages,
        "lead_snapshot": _lead_snapshot_for_detail(lead, messages),
    }
    n_mail = sum(1 for m in messages if m.get("kind") == "email")
    n_li = sum(1 for m in messages if m.get("kind") == "linkedin")
    recipient = (
        f"{len(contacts)} contact(s) · {n_mail} mail · {n_li} LinkedIn"
        if contacts
        else f"{n_mail} mail · {n_li} LinkedIn"
    )
    return {
        "lead_id": lead.get("lead_id"),
        "company": lead.get("name"),
        "channel": COMPANY_CHANNEL,
        "recipient": recipient,
        "subject": subject_line(lead),
        "body": json.dumps(bundle, ensure_ascii=False),
        "mode": "dry_run",
        "would_send": False,
        "note": "company bundle",
        "bundle": bundle,
    }


def parse_queue_bundle(row: dict | None) -> dict | None:
    if not row:
        return None
    raw = row.get("body") or ""
    if not isinstance(raw, str) or not raw.strip().startswith("{"):
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("kind") != "company_bundle":
        return None
    return data


def bundle_from_any(row: dict | None) -> dict:
    """Normalize queue row into a display bundle (legacy single-body rows included)."""
    parsed = parse_queue_bundle(row)
    if parsed:
        return parsed
    row = row or {}
    kind = "linkedin" if (row.get("channel") or "") == "linkedin" else "email"
    body = (row.get("body") or "").strip()
    return {
        "version": 0,
        "kind": "legacy",
        "lead_id": row.get("lead_id") or "",
        "company": row.get("company") or "",
        "domain": "",
        "search_name": "",
        "icp_text": "",
        "signal": {},
        "signal_text": "",
        "contacts": [],
        "selected_messages": (
            [
                {
                    "target_key": "legacy",
                    "scope": "legacy",
                    "person_name": row.get("recipient") or "",
                    "person_role": "",
                    "kind": kind,
                    "body": body,
                }
            ]
            if body
            else []
        ),
        "lead_snapshot": None,
    }


def format_contacts_line(contacts: list[dict] | None) -> str:
    names = []
    for c in contacts or []:
        name = (c.get("name") or "").strip()
        role = (c.get("role") or "").strip()
        if name and role:
            names.append(f"{name} ({role})")
        elif name:
            names.append(name)
    return " · ".join(names) if names else "—"


def search_label_for_lead(lead: dict | None, *, search_name: str = "", icp_text: str = "") -> str:
    """Prefer explicit search name, else first line / short ICP text."""
    from .memory import default_search_name, resolve_search_name

    label = (search_name or "").strip()
    if label:
        return label
    brief = (icp_text or "").strip()
    if lead and isinstance(lead, dict):
        brief = brief or (lead.get("icp_text") or lead.get("discovery_web_query") or "")
        # When we have a query session-like dict
        if lead.get("label") or lead.get("icp_text"):
            return resolve_search_name(
                {
                    "label": lead.get("label") or search_name,
                    "icp_text": lead.get("icp_text") or brief,
                    "service_line": lead.get("service_line") or "",
                }
            )
    if brief:
        return default_search_name(brief)
    return ""


def enrich_queue_bundle(
    bundle: dict | None,
    *,
    lead: dict | None = None,
    pipeline_item: dict | None = None,
) -> dict:
    """Fill search / signal / contacts for display (new bundles + legacy rows)."""
    data = dict(bundle or {})
    pipe = pipeline_item or {}
    lead = lead if isinstance(lead, dict) else None

    search_name = (data.get("search_name") or "").strip() or (pipe.get("search_name") or "").strip()
    icp_text = (data.get("icp_text") or "").strip() or (pipe.get("icp_text") or "").strip()
    if lead and not icp_text:
        icp_text = (lead.get("icp_text") or "").strip()
    if not search_name:
        search_name = search_label_for_lead(lead, search_name=search_name, icp_text=icp_text)
    data["search_name"] = search_name
    data["icp_text"] = icp_text

    signal_text = (data.get("signal_text") or "").strip()
    if not signal_text and lead:
        signal_text = signal_summary(lead)
    if not signal_text:
        sig = data.get("signal") if isinstance(data.get("signal"), dict) else {}
        kind = (sig.get("type") or "").replace("_", " ").strip()
        text = (sig.get("summary") or "").strip()
        signal_text = f"{kind}: {text}" if kind and text else (text or kind)
    data["signal_text"] = signal_text

    contacts = data.get("contacts") if isinstance(data.get("contacts"), list) else []
    if (not contacts) and lead:
        contacts = contacts_summary(lead)
    if not contacts and pipe:
        person = (pipe.get("person_name") or "").strip()
        role = (pipe.get("person_role") or "").strip()
        if person:
            contacts = [{"name": person, "role": role, "email": pipe.get("person_email") or ""}]
    data["contacts"] = contacts
    return data
