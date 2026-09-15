"""Classify leads into verified-people vs approach-channels vs unresolved."""

from __future__ import annotations

from .schemas import CompanyLead


def classify_result_section(lead: CompanyLead | dict) -> str:
    """
    verified_people — at least one fully verified playbook contact with person-tied channel
    approach_channels — no verified person, but company approach channel exists
    unresolved — neither (omit from main UI sections)
    """
    if hasattr(lead, "model_dump"):
        data = lead.model_dump()
    else:
        data = lead

    sig = data.get("signal") or {}
    # Weak signals never promote to verified_people section
    if sig.get("confidence") in {"UNVERIFIED", "LOW"}:
        if data.get("approach_channels") or data.get("best_approach_channel"):
            return "approach_channels"
        return "unresolved"

    verified = data.get("verified_contacts") or []
    if not verified:
        # Fall back: contacts explicitly marked person_verified
        verified = [
            c
            for c in (data.get("contacts") or [])
            if (c.get("person_verified") if isinstance(c, dict) else getattr(c, "person_verified", False))
        ]
    primary = data.get("contact") or {}
    primary_verified = False
    if isinstance(primary, dict):
        primary_verified = bool(primary.get("person_verified")) and primary.get("name") not in {
            "not_found",
            "unknown",
            "",
            None,
        }
    else:
        primary_verified = bool(getattr(primary, "person_verified", False)) and getattr(
            primary, "name", ""
        ) not in {"not_found", "unknown", ""}

    if verified or primary_verified:
        return "verified_people"

    if data.get("approach_channels") or data.get("best_approach_channel"):
        return "approach_channels"

    return "unresolved"
