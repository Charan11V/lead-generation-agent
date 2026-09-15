"""Apollo.io / DAG Leads friendly exports — open profiles with your browser plugins."""

from __future__ import annotations

import csv
import io
from pathlib import Path


def _split_name(full: str) -> tuple[str, str]:
    parts = [p for p in (full or "").strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def plugin_rows(leads: list[dict]) -> list[dict]:
    """One row per person across all leads — ready for Apollo / DAG / LinkedIn open."""
    rows: list[dict] = []
    for lead in leads:
        company = lead.get("name") or ""
        domain = lead.get("domain") or ""
        website = lead.get("website") or ""
        people = lead.get("contacts") or []
        if not people and lead.get("contact"):
            people = [lead["contact"]]
        for p in people:
            name = p.get("name") or ""
            if name.lower() in {"not_found", "unknown", ""}:
                continue
            first, last = _split_name(name)
            linkedin = p.get("linkedin_url") or ""
            other = p.get("other_social") or []
            if isinstance(other, str):
                other = [other] if other else []
            rows.append(
                {
                    "First Name": first,
                    "Last Name": last,
                    "Full Name": name,
                    "Title": p.get("role") or "",
                    "Company": company,
                    "Domain": domain if domain != "unknown" else "",
                    "Website": website if website != "not_found" else "",
                    "Email": (p.get("email") or "").strip(),
                    "Phone": (p.get("phone") or "").strip(),
                    "LinkedIn URL": linkedin,
                    "Twitter/X URL": (p.get("twitter_url") or "").strip(),
                    "Other Social": " | ".join(other),
                    "Best Channel": p.get("best_channel") or "",
                    "Primary": "yes" if p.get("is_primary") else "no",
                    "Relevance Score": p.get("relevance_score") or "",
                    "Apollo Hint": p.get("apollo_hint")
                    or (f"Open LinkedIn: {linkedin}" if linkedin else f"Apollo search: {name} · {company}"),
                    "Lead ID": lead.get("lead_id") or "",
                }
            )
    return rows


def _has_social(row: dict) -> bool:
    if (row.get("LinkedIn URL") or "").strip():
        return True
    if (row.get("Twitter/X URL") or "").strip():
        return True
    other = (row.get("Other Social") or "").strip().lower()
    if not other:
        return False
    # Instagram or any other social handle/URL
    return True


def enrich_rows(leads: list[dict]) -> list[dict]:
    """People missing email AND phone, but with LinkedIn / X / other social to approach."""
    out = []
    for row in plugin_rows(leads):
        has_email = bool((row.get("Email") or "").strip())
        has_phone = bool((row.get("Phone") or "").strip())
        if has_email or has_phone:
            continue
        if _has_social(row):
            out.append(row)
    return out


def contact_rows(leads: list[dict]) -> list[dict]:
    """People with a found email and/or phone."""
    out = []
    for row in plugin_rows(leads):
        has_email = bool((row.get("Email") or "").strip())
        has_phone = bool((row.get("Phone") or "").strip())
        if has_email or has_phone:
            out.append(row)
    return out


def apollo_csv_text(leads: list[dict]) -> str:
    rows = plugin_rows(leads)
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def linkedin_url_list(leads: list[dict]) -> str:
    """One LinkedIn URL per line — open each with Apollo/DAG extension installed."""
    urls: list[str] = []
    seen: set[str] = set()
    for row in plugin_rows(leads):
        url = (row.get("LinkedIn URL") or "").strip()
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return "\n".join(urls)


def apollo_search_clipboard(leads: list[dict]) -> str:
    """Name + company + domain lines for pasting into Apollo search when LinkedIn is missing."""
    lines: list[str] = []
    for row in plugin_rows(leads):
        if row.get("LinkedIn URL"):
            continue
        bits = [row.get("Full Name"), row.get("Company"), row.get("Domain") or row.get("Title")]
        line = " | ".join(b for b in bits if b)
        if line:
            lines.append(line)
    return "\n".join(lines)


def write_plugin_exports(leads: list[dict], directory: str | Path) -> dict[str, Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    csv_path = directory / "apollo_dag_enrich.csv"
    csv_path.write_text(apollo_csv_text(leads), encoding="utf-8")
    paths["csv"] = csv_path
    li = linkedin_url_list(leads)
    li_path = directory / "linkedin_profiles.txt"
    li_path.write_text(li, encoding="utf-8")
    paths["linkedin"] = li_path
    search_path = directory / "apollo_search_fallback.txt"
    search_path.write_text(apollo_search_clipboard(leads), encoding="utf-8")
    paths["search"] = search_path
    return paths
