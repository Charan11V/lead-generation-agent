"""Frequency-branded Streamlit chrome."""

from __future__ import annotations

import html
import re


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Outfit:wght@380;460;560;650&display=swap');

html, body, [data-testid="stAppViewContainer"], .stApp {
  background: #07090b !important;
  color: #e8eef0;
  font-family: "Outfit", sans-serif;
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { visibility: hidden; }
#MainMenu, footer, [data-testid="stStatusWidget"] { visibility: hidden; }
.block-container { padding-top: 1.2rem; max-width: 1380px; }

section[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #0b1114 0%, #07090b 100%);
  border-right: 1px solid #1a2a2c;
}
section[data-testid="stSidebar"] * { font-family: "Outfit", sans-serif; }

.fx-mark {
  display: flex; gap: 12px; align-items: center; margin-bottom: 8px;
}
.fx-fin {
  width: 28px; height: 28px;
  background: conic-gradient(from 200deg, #00e0c6, #148f86, #00e0c6);
  clip-path: polygon(12% 88%, 50% 6%, 88% 88%, 50% 64%);
  filter: drop-shadow(0 0 10px rgba(0,224,198,.45));
}
.fx-word {
  font-family: "Instrument Serif", serif;
  font-size: 28px; letter-spacing: .12em; color: #00e0c6; margin: 0;
}
.fx-sub { color: #8a9a9e; font-size: 11px; letter-spacing: .28em; text-transform: uppercase; margin: 0 0 18px 40px; }

.fx-hero {
  border: 1px solid #1c3334;
  background:
    radial-gradient(1200px 280px at 10% -10%, rgba(0,224,198,.12), transparent 50%),
    linear-gradient(180deg, #0e1518 0%, #0a1012 100%);
  padding: 22px 26px 18px;
  border-radius: 18px;
  margin-bottom: 18px;
}
.fx-hero h1 {
  font-family: "Instrument Serif", serif;
  font-size: 34px; font-weight: 400; margin: 0 0 6px;
  color: #f4fbfb;
}
.fx-hero h1 em { color: #00e0c6; font-style: italic; }
.fx-hero p { color: #9aabae; margin: 0; font-size: 14.5px; max-width: 720px; line-height: 1.5; }
.fx-pills { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
.fx-pill {
  font-size: 11px; letter-spacing: .08em; text-transform: uppercase;
  border: 1px solid #1e3d3c; color: #9fe9de; padding: 5px 10px; border-radius: 999px;
}

.fx-funnel {
  display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin: 8px 0 18px;
}
.fx-step {
  background: #101618; border: 1px solid #1b2e30; border-radius: 14px; padding: 12px 12px 10px;
}
.fx-step .n { font-size: 22px; color: #00e0c6; font-weight: 650; }
.fx-step .l { font-size: 11px; color: #8a9a9e; letter-spacing: .06em; text-transform: uppercase; }

.fx-card {
  background: #101618; border: 1px solid #1b2e30; border-radius: 16px; padding: 14px 16px; margin-bottom: 10px;
}
.fx-card.active { border-color: #00e0c6; box-shadow: 0 0 0 1px rgba(0,224,198,.25); }
.fx-row { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
.fx-name { font-size: 16px; font-weight: 560; color: #f2f8f8; margin: 0; }
.fx-meta { color: #8a9a9e; font-size: 12px; margin: 4px 0 0; }
.fx-score {
  min-width: 46px; height: 46px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  border: 2px solid #00e0c6; color: #00e0c6; font-weight: 650;
}
.fx-badges { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.badge {
  font-size: 10px; letter-spacing: .08em; text-transform: uppercase;
  padding: 3px 8px; border-radius: 999px; border: 1px solid #2a3f40; color: #c5d5d6;
}
.badge.high { border-color: #1e6b4a; color: #6ee7b7; }
.badge.med { border-color: #6b5a1e; color: #e0c36a; }
.badge.low, .badge.unver { border-color: #6b2a1e; color: #f0a090; }
.badge.pending { border-color: #245c5a; color: #9fe9de; }

.fx-panel {
  background: #0e1518; border: 1px solid #1b2e30; border-radius: 18px; padding: 20px 22px;
}
.fx-k { font-size: 11px; letter-spacing: .16em; text-transform: uppercase; color: #7fdad0; margin: 18px 0 8px; }
.fx-k:first-child { margin-top: 0; }
.fx-letter {
  background: #0a1012; border-left: 3px solid #00e0c6; padding: 14px 16px; border-radius: 0 12px 12px 0;
  white-space: pre-wrap; color: #dce8e8; line-height: 1.55; font-size: 14.5px;
}
.fx-src a { color: #00e0c6; text-decoration: none; }
.reason { color: #c5d3d4; font-size: 13.5px; line-height: 1.45; margin: 0 0 6px; padding-left: 10px; border-left: 2px solid #1e3d3c; }

.stButton>button {
  background: #00e0c6 !important;
  color: #04110f !important;
  border: 0 !important;
  font-weight: 650 !important;
  border-radius: 12px !important;
  padding: 0.7rem 1.1rem !important;
}
.stButton>button:hover { background: #20f0d6 !important; color: #04110f !important; }
div[data-testid="stTextArea"] textarea,
div[data-testid="stTextInput"] input,
div[data-testid="stSelectbox"] div {
  color: #e8eef0 !important;
}
div[data-testid="stTextArea"] textarea {
  background: #0a1012 !important;
  border: 1px solid #1b2e30 !important;
  min-height: 96px;
}
label, .stMarkdown, [data-testid="stWidgetLabel"] p {
  color: #c5d5d6 !important;
}
[data-testid="stSidebarCollapseButton"] {
  visibility: visible !important;
}

div[role="radiogroup"] label {
  background: #101618 !important;
  border: 1px solid #1b2e30 !important;
  border-radius: 12px !important;
  padding: 8px 12px !important;
  margin-bottom: 6px !important;
}
div[role="radiogroup"] label:has(input:checked) {
  border-color: #00e0c6 !important;
}
</style>
"""


def key_status(openai_ok: bool, tavily_ok: bool) -> str:
    o = "OpenAI loaded" if openai_ok else "OpenAI missing"
    t = "Tavily loaded" if tavily_ok else "Tavily missing"
    oc = "high" if openai_ok else "low"
    tc = "high" if tavily_ok else "low"
    return (
        f'<div class="fx-badges"><span class="badge {oc}">{html.escape(o)}</span>'
        f'<span class="badge {tc}">{html.escape(t)}</span></div>'
    )


def inject() -> str:
    return CSS


def hero() -> str:
    return """
<div class="fx-hero">
  <div class="fx-mark"><div class="fx-fin"></div><p class="fx-word">FREQUENCY</p></div>
  <div class="fx-sub">Leadership &amp; talent consulting</div>
  <h1>Lead Intelligence <em>Agent</em></h1>
  <p>Public-web research → verified signals → explainable scores → Frequency-proofed first-touch. Nothing sends. A human approves every line.</p>
  <div class="fx-pills">
    <span class="fx-pill">Precision</span>
    <span class="fx-pill">Poise</span>
    <span class="fx-pill">Intrigue</span>
    <span class="fx-pill">Human review</span>
    <span class="fx-pill">No auto-send</span>
  </div>
</div>
"""


def funnel_html(funnel: dict) -> str:
    steps = [
        ("Queries", funnel.get("queries") or 0),
        ("URLs", funnel.get("hits") or 0),
        ("New cos", funnel.get("companies") or 0),
        ("Skipped", funnel.get("skipped_this_run") or funnel.get("skipped_seen") or 0),
        ("Usable", funnel.get("verified") or 0),
        ("Queued", funnel.get("queued") or 0),
    ]
    cells = "".join(
        f'<div class="fx-step"><div class="n">{html.escape(str(n))}</div><div class="l">{html.escape(label)}</div></div>'
        for label, n in steps
    )
    return f'<div class="fx-funnel">{cells}</div>'


def _conf_class(conf: str) -> str:
    c = (conf or "").upper()
    if c == "HIGH":
        return "high"
    if c == "MEDIUM":
        return "med"
    if c == "UNVERIFIED":
        return "unver"
    return "low"


def lead_card(lead: dict, active: bool = False) -> str:
    score = (lead.get("score") or {}).get("total") or 0
    signal = lead.get("signal") or {}
    contact = lead.get("contact") or {}
    all_contacts = lead.get("contacts") or []
    cls = "fx-card active" if active else "fx-card"
    name = html.escape(lead.get("name") or "")
    industry = html.escape(lead.get("industry") or "unknown")
    city = html.escape(lead.get("city") or "")
    country = html.escape(lead.get("country") or "")
    loc = ", ".join(x for x in [city, country] if x and x != "unknown")
    summary = html.escape((signal.get("summary") or "")[:140])
    conf = html.escape(signal.get("confidence") or "UNVERIFIED")
    status = html.escape(lead.get("review_status") or "pending")
    contact_s = html.escape(f"{contact.get('name') or 'not_found'} · {contact.get('role') or ''}")
    if contact.get("email"):
        contact_s += html.escape(f" · {contact['email']}")
    elif contact.get("linkedin_url"):
        contact_s += " · LinkedIn"
    if len(all_contacts) > 1:
        contact_s += html.escape(f" (+{len(all_contacts) - 1} alt)")
    return f"""
<div class="{cls}">
  <div class="fx-row">
    <div>
      <p class="fx-name">{name}</p>
      <p class="fx-meta">{industry}{(' · ' + loc) if loc else ''}<br>{contact_s}</p>
    </div>
    <div class="fx-score">{score}</div>
  </div>
  <p class="fx-meta" style="margin-top:8px">{summary}</p>
  <div class="fx-badges">
    <span class="badge {_conf_class(conf)}">{conf}</span>
    <span class="badge pending">{status}</span>
  </div>
</div>
"""


def _esc(text: str) -> str:
    return html.escape(text or "")


def _link(url: str, label: str | None = None) -> str:
    if not url:
        return "—"
    lab = html.escape(label or url)
    return f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{lab}</a>'


def detail_html(lead: dict) -> str:
    score = lead.get("score") or {}
    signal = lead.get("signal") or {}
    contact = lead.get("contact") or {}
    all_contacts = lead.get("contacts") or []
    reasons = "".join(f'<p class="reason">{_esc(r)}</p>' for r in (score.get("reasons") or []))
    sources = signal.get("sources") or []
    src_html = "".join(
        f'<div class="fx-src">· <a href="{html.escape(s.get("url") or "#")}" target="_blank">{_esc(s.get("title") or s.get("url"))}</a> '
        f'· {_esc(s.get("date") or "date unknown")} · {_esc(s.get("publisher") or "")}</div>'
        for s in sources
    )
    if all_contacts:
        contacts_html = "".join(
            f'<p class="reason">#{c.get("rank", "?")} {_esc(c.get("name"))} · {_esc(c.get("role"))}'
            f'{" ★ primary" if c.get("is_primary") else ""}<br>'
            f'Score {c.get("relevance_score", 0)} · {_esc(c.get("confidence"))} · usable={c.get("usable_in_outreach")}<br>'
            f'{_esc(c.get("why"))}<br>{_esc(c.get("likelihood_reason"))}<br>'
            f'Email: {_esc(c.get("email") or "—")} · Phone: {_esc(c.get("phone") or "—")}<br>'
            f'LinkedIn: {_link(c.get("linkedin_url"))} · X: {_link(c.get("twitter_url"))}<br>'
            f'Best channel: {_esc(c.get("best_channel") or "—")}<br>'
            f'{_esc(c.get("apollo_hint") or "")}<br>'
            f'Source: {_esc(c.get("source_url") or "not_found")}</p>'
            for c in all_contacts
        )
    else:
        contacts_html = (
            f'<p class="reason">{_esc(contact.get("name"))} · {_esc(contact.get("role"))}<br>'
            f'{_esc(contact.get("why"))}<br>'
            f'Email: {_esc(contact.get("email") or "—")} · Phone: {_esc(contact.get("phone") or "—")}<br>'
            f'LinkedIn: {_link(contact.get("linkedin_url"))} · X: {_link(contact.get("twitter_url"))}<br>'
            f'Source: {_esc(contact.get("source_url") or "not_found")} · '
            f'usable={contact.get("usable_in_outreach")}</p>'
        )
    proofs = "".join(
        f'<p class="reason"><b>{_esc(p.get("company"))}</b> — {_esc(", ".join(p.get("roles_placed") or []))}<br>'
        f'{_esc(p.get("outcome"))}<br><i>{_esc(p.get("why_matched"))}</i></p>'
        for p in (lead.get("proofs") or [])
    )
    flags = lead.get("qa_flags") or []
    flag_html = "".join(f'<p class="reason">{_esc(f)}</p>' for f in flags) or '<p class="reason">No QA flags.</p>'
    uncertainty = lead.get("field_uncertainty") or []
    unc_html = "".join(f'<p class="reason">{_esc(u)}</p>' for u in uncertainty) or '<p class="reason">None flagged.</p>'
    meta_bits = []
    if lead.get("discovery_web_query"):
        meta_bits.append(f"Found via web query: {_esc(lead.get('discovery_web_query'))}")
    if lead.get("linked_at"):
        meta_bits.append(f"Linked {_esc(lead.get('linked_at'))}")
    if lead.get("query_id"):
        meta_bits.append(f"Query session {_esc(lead.get('query_id'))}")
    meta_html = "".join(f'<p class="reason">{b}</p>' for b in meta_bits)
    why_int = lead.get("why_interested") or ""
    return f"""
<div class="fx-panel">
  <div class="fx-k">Why this lead · {score.get("total", 0)} / 100</div>
  <p class="reason">{_esc(score.get("why") or "")}</p>
  {reasons}
  <div class="fx-k">Why they might be interested in Frequency</div>
  <p class="reason">{_esc(why_int) if why_int else "Interest brief not generated yet."}</p>
  {meta_html}
  <div class="fx-k">Signal · { _esc(signal.get("confidence") or "") } · { _esc(signal.get("type") or "") }</div>
  <p class="reason">{_esc(signal.get("summary") or "")}</p>
  <p class="reason">Evidence: {_esc(signal.get("evidence_quote") or "n/a")}</p>
  {src_html}
  <div class="fx-k">Outreach targets · ranked by likelihood</div>
  {contacts_html}
  <div class="fx-k">Frequency proof points</div>
  {proofs}
  <div class="fx-k">Email draft</div>
  <div class="fx-letter">{_esc(lead.get("email_draft") or "")}</div>
  <div class="fx-k">LinkedIn note</div>
  <div class="fx-letter">{_esc(lead.get("linkedin_note") or "")}</div>
  <div class="fx-k">QA flags</div>
  {flag_html}
  <div class="fx-k">Uncertainty</div>
  {unc_html}
</div>
"""
