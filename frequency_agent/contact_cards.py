"""Contact card HTML helpers for Direct / Indirect results views.

HTML is emitted compact (no leading indentation / blank lines) so Streamlit's
markdown path cannot treat nested blocks as code fences. Prefer ``st.html`` for
rendering; builders still stay markdown-safe for ``st.markdown(..., unsafe_allow_html=True)``.
"""

from __future__ import annotations

import html
import re


def _e(text: str) -> str:
    return html.escape(text or "")


def _draft_body(text: str) -> str:
    """Escape draft text and keep line breaks as HTML (avoids markdown blank-line breaks)."""
    return _e(text).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _lk(url: str, label: str | None = None) -> str:
    if not url:
        return "—"
    lab = html.escape(label or re.sub(r"^https?://(www\.)?", "", url).rstrip("/"))
    return f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{lab}</a>'


def section_banner_html(kind: str, count: int) -> str:
    if kind == "direct":
        return (
            '<div class="fx-banner">Direct <em>contacts</em></div>'
            '<p class="fx-banner-sub">Exact people to approach for this ICP — every channel we verified. '
            "Edit and select outreach messages on the Results tab.</p>"
            f'<div class="fx-rail"><span class="fx-pill"><span class="n">{count}</span> ready</span></div>'
        )
    return (
        '<div class="fx-banner">Indirect <em>contacts</em></div>'
        '<p class="fx-banner-sub">No verified DM yet — best company channels for this ICP. '
        "Edit and select outreach messages on the Results tab.</p>"
        f'<div class="fx-rail"><span class="fx-pill indirect"><span class="n">{count}</span> channels</span></div>'
    )


def _person_channel_chips(person: dict) -> str:
    chips = []
    if person.get("email"):
        chips.append(
            f'<span class="fx-chan-chip">✉ <a href="mailto:{html.escape(person["email"])}">{_e(person["email"])}</a></span>'
        )
    if person.get("phone"):
        chips.append(f'<span class="fx-chan-chip">☎ {_e(person["phone"])}</span>')
    if person.get("linkedin_url"):
        chips.append(f'<span class="fx-chan-chip">{_lk(person["linkedin_url"], "LinkedIn")}</span>')
    if person.get("twitter_url"):
        chips.append(f'<span class="fx-chan-chip">{_lk(person["twitter_url"], "X")}</span>')
    for u in (person.get("other_social") or [])[:3]:
        chips.append(f'<span class="fx-chan-chip">{_lk(u)}</span>')
    if not chips:
        chips.append('<span class="fx-chan-chip">No public channel yet</span>')
    return "".join(chips)


def _draft_pair_html(email: str, linkedin: str, *, who: str = "") -> str:
    """Render available outreach drafts — email, LinkedIn, or both — clearly labeled."""
    who_bit = f" for {_e(who)}" if who else ""
    parts: list[str] = []
    if email:
        parts.append(
            f'<p class="fx-mail-label">Outreach message{who_bit}</p>'
            '<p class="fx-hit-meta" style="margin:0 0 6px">Reusable — email, LinkedIn InMail, or message</p>'
            f'<div class="fx-mail">{_draft_body(email)}</div>'
        )
    if linkedin:
        label_style = ' style="margin-top:12px"' if parts else ""
        parts.append(
            f'<p class="fx-mail-label"{label_style}>LinkedIn note{who_bit}</p>'
            f'<div class="fx-mail">{_draft_body(linkedin)}</div>'
        )
    if not parts:
        return (
            '<div class="fx-drafts">'
            '<p class="fx-hit-meta">Outreach drafts pending — re-run search to generate.</p>'
            "</div>"
        )
    return f'<div class="fx-drafts">{"".join(parts)}</div>'


def direct_person_card_html(lead: dict, person: dict, *, delay_ms: int = 0) -> str:
    score = (lead.get("score") or {}).get("total") or 0
    company = lead.get("name") or "—"
    industry = lead.get("industry") or ""
    city = lead.get("city") or ""
    country = lead.get("country") or ""
    loc = ", ".join(x for x in [city, country] if x and x != "unknown")
    website = lead.get("website") or ""
    meta_bits = [x for x in [industry, loc] if x and x != "unknown"]
    if website and website not in {"not_found", "unknown"}:
        meta_bits.append(_lk(website))
    meta = " · ".join(meta_bits)
    name = person.get("name") or "not_found"
    role = person.get("role") or ""
    why = person.get("why") or person.get("likelihood_reason") or ""
    why_html = f'<p class="fx-hit-meta" style="margin-top:10px">{_e(why)}</p>' if why else ""
    # Compact, unindented HTML — indentation triggers Streamlit markdown code blocks.
    return (
        f'<div class="fx-hit" style="animation-delay:{delay_ms}ms">'
        '<div class="fx-hit-inner">'
        '<div class="fx-hit-top">'
        "<div>"
        f'<h3 class="fx-hit-co">{_e(company)}</h3>'
        f'<p class="fx-hit-meta">{meta}</p>'
        "</div>"
        f'<div class="fx-hit-score"><div class="n">{int(score)}</div><div class="l">score</div></div>'
        "</div>"
        '<div class="fx-person-block">'
        '<div class="fx-who">'
        f"<h4>{_e(name)}</h4>"
        f'<p class="role">{_e(role)}</p>'
        f"<div>{_person_channel_chips(person)}</div>"
        f"{why_html}"
        "</div>"
        '<p class="fx-hit-meta" style="margin-top:10px">Edit &amp; select messages on the Results tab for this company.</p>'
        "</div>"
        "</div>"
        "</div>"
    )


def indirect_company_card_html(lead: dict, *, delay_ms: int = 0) -> str:
    score = (lead.get("score") or {}).get("total") or 0
    company = lead.get("name") or "—"
    industry = lead.get("industry") or ""
    city = lead.get("city") or ""
    country = lead.get("country") or ""
    loc = ", ".join(x for x in [city, country] if x and x != "unknown")
    website = lead.get("website") or ""
    meta_bits = [x for x in [industry, loc] if x and x != "unknown"]
    if website and website not in {"not_found", "unknown"}:
        meta_bits.append(_lk(website))
    meta = " · ".join(meta_bits)
    role = (lead.get("contact") or {}).get("role") or "Decision-maker desk"
    chips = []
    for ch in lead.get("approach_channels") or []:
        kind = ch.get("kind") or ""
        label = ch.get("label") or kind
        value = ch.get("value") or ""
        if kind == "email":
            chips.append(
                f'<span class="fx-chan-chip">{_e(label)} · '
                f'<a href="mailto:{html.escape(value)}">{_e(value)}</a></span>'
            )
        elif str(value).startswith("http"):
            chips.append(f'<span class="fx-chan-chip">{_e(label)} · {_lk(value)}</span>')
        else:
            chips.append(f'<span class="fx-chan-chip">{_e(label)} · {_e(value)}</span>')
    if not chips and lead.get("best_approach_channel"):
        chips.append(f'<span class="fx-chan-chip">{_e(lead["best_approach_channel"])}</span>')
    if not chips:
        chips.append('<span class="fx-chan-chip">No channel sourced</span>')
    return (
        f'<div class="fx-hit indirect" style="animation-delay:{delay_ms}ms">'
        '<div class="fx-hit-inner">'
        '<div class="fx-hit-top">'
        "<div>"
        f'<h3 class="fx-hit-co">{_e(company)}</h3>'
        f'<p class="fx-hit-meta">{meta}</p>'
        "</div>"
        f'<div class="fx-hit-score"><div class="n">{int(score)}</div><div class="l">score</div></div>'
        "</div>"
        '<div class="fx-person-block">'
        '<div class="fx-who">'
        "<h4>Best approach path</h4>"
        f'<p class="role">Aim for {_e(role)} · no verified named DM</p>'
        f'<div>{"".join(chips)}</div>'
        "</div>"
        '<p class="fx-hit-meta" style="margin-top:10px">Edit &amp; select messages on the Results tab for this company.</p>'
        "</div>"
        "</div>"
        "</div>"
    )


def iter_direct_people(leads: list[dict]) -> list[tuple[dict, dict]]:
    out: list[tuple[dict, dict]] = []
    for lead in leads:
        sec = lead.get("result_section") or ""
        if sec == "approach_channels":
            continue
        people = [
            p
            for p in (lead.get("verified_contacts") or lead.get("contacts") or [])
            if (p.get("name") or "").lower() not in {"", "unknown", "not_found"}
        ]
        if not people:
            c = lead.get("contact") or {}
            if (c.get("name") or "").lower() not in {"", "unknown", "not_found"}:
                people = [c]
        if not people:
            continue
        for p in people:
            out.append((lead, p))
    out.sort(key=lambda pair: ((pair[0].get("score") or {}).get("total") or 0), reverse=True)
    return out


def iter_indirect_leads(leads: list[dict]) -> list[dict]:
    rows = [l for l in leads if (l.get("result_section") or "") == "approach_channels"]
    rows.sort(key=lambda l: ((l.get("score") or {}).get("total") or 0), reverse=True)
    return rows
