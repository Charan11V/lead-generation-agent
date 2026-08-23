"""CSV / JSON export for the submission sample_output artifact."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


COLUMNS = [
    "Company",
    "Website",
    "Industry",
    "Contact",
    "Contact Role",
    "Email",
    "Phone",
    "LinkedIn URL",
    "Twitter/X URL",
    "Best Channel",
    "All Contacts (ranked)",
    "ICP Fit",
    "Signal",
    "Signal Date",
    "Source",
    "Signal Confidence",
    "Overall Score",
    "Score Reasoning",
    "Frequency Proof Points",
    "Draft Outreach",
    "LinkedIn Note",
    "Review Status",
    "QA Flags",
    "Field Uncertainty",
]


def leads_to_rows(leads: list[dict]) -> list[dict]:
    rows = []
    for lead in leads:
        signal = lead.get("signal") or {}
        sources = signal.get("sources") or []
        source = sources[0]["url"] if sources else ""
        proofs = lead.get("proofs") or []
        proof_txt = " | ".join(
            f"{p.get('company')}: {p.get('outcome')}" for p in proofs
        )
        score = lead.get("score") or {}
        contact = lead.get("contact") or {}
        all_contacts = lead.get("contacts") or []
        alt_txt = " | ".join(
            f"#{c.get('rank')} {c.get('name')} ({c.get('role')}, score={c.get('relevance_score')}"
            f", email={c.get('email') or '-'}, li={c.get('linkedin_url') or '-'})"
            for c in all_contacts
        )
        rows.append(
            {
                "Company": lead.get("name"),
                "Website": lead.get("website"),
                "Industry": lead.get("industry"),
                "Contact": contact.get("name"),
                "Contact Role": contact.get("role"),
                "Email": contact.get("email") or "",
                "Phone": contact.get("phone") or "",
                "LinkedIn URL": contact.get("linkedin_url") or "",
                "Twitter/X URL": contact.get("twitter_url") or "",
                "Best Channel": contact.get("best_channel") or "",
                "All Contacts (ranked)": alt_txt,
                "ICP Fit": score.get("icp_fit"),
                "Signal": signal.get("summary"),
                "Signal Date": signal.get("date"),
                "Source": source,
                "Signal Confidence": signal.get("confidence"),
                "Overall Score": score.get("total"),
                "Score Reasoning": score.get("why"),
                "Frequency Proof Points": proof_txt,
                "Draft Outreach": lead.get("email_draft"),
                "LinkedIn Note": lead.get("linkedin_note"),
                "Review Status": lead.get("review_status"),
                "QA Flags": " | ".join(lead.get("qa_flags") or []),
                "Field Uncertainty": " | ".join(lead.get("field_uncertainty") or []),
            }
        )
    return rows


def export_leads(leads: list[dict], directory: str | Path) -> tuple[Path, Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = directory / "sample_output.csv"
    json_path = directory / "sample_output.json"
    rows = leads_to_rows(leads)
    pd.DataFrame(rows, columns=COLUMNS).to_csv(csv_path, index=False)
    json_path.write_text(json.dumps(leads, indent=2, ensure_ascii=False), encoding="utf-8")
    return csv_path, json_path
