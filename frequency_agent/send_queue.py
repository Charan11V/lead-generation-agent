"""Dry-run send queue. Nothing ever leaves the machine — no SMTP, no LinkedIn, no WhatsApp."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


BLOCKED_PREFIX = "[BLOCKED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def can_enqueue(lead: dict, *, require_selection: bool = True) -> tuple[bool, str]:
    """Gate for queueing. Prefer selected messages when require_selection is True."""
    if require_selection:
        from .outreach_queue import can_enqueue_company

        return can_enqueue_company(lead)
    status = (lead.get("review_status") or "pending").lower()
    if status == "rejected":
        return False, "Rejected leads cannot enter the send queue."
    body = (lead.get("email_draft") or "").strip()
    if not body:
        return False, "Draft is empty — will not queue."
    return True, ""


def recipient_label(lead: dict) -> str:
    contact = lead.get("contact") or {}
    name = contact.get("name") or "not_found"
    role = contact.get("role") or "unknown role"
    channels = []
    if contact.get("email"):
        channels.append(contact["email"])
    if contact.get("phone"):
        channels.append(contact["phone"])
    if contact.get("linkedin_url"):
        channels.append(contact["linkedin_url"])
    elif contact.get("twitter_url"):
        channels.append(contact["twitter_url"])
    channel_note = f" · {channels[0]}" if channels else ""
    alts = [
        c for c in (lead.get("contacts") or [])
        if not c.get("is_primary") and c.get("usable_in_outreach") and c.get("name") not in {"not_found", "unknown", ""}
    ]
    alt_note = ""
    if alts:
        alt_note = " | Alt: " + "; ".join(f"{c.get('name')} ({c.get('role')})" for c in alts[:3])
    if name in {"not_found", "unknown", ""}:
        return f"{role} at {lead.get('name')} (name not_found — do not invent){channel_note}{alt_note}"
    return f"{name}, {role} at {lead.get('name')}{channel_note}{alt_note}"


def subject_line(lead: dict) -> str:
    signal = lead.get("signal") or {}
    kind = (signal.get("type") or "note").replace("_", " ")
    return f"{lead.get('name')} — {kind}"


def queue_payload(lead: dict, channel: str = "email") -> dict:
    body = lead.get("email_draft") if channel == "email" else lead.get("linkedin_note")
    return {
        "lead_id": lead.get("lead_id"),
        "company": lead.get("name"),
        "channel": channel,
        "recipient": recipient_label(lead),
        "subject": subject_line(lead) if channel == "email" else "",
        "body": (body or "").strip(),
        "mode": "dry_run",
        "would_send": False,
    }


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
