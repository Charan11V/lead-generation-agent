"""ICP helpers — service-line inference and display labels."""

from __future__ import annotations

from .schemas import ServiceLine
from .memory import normalize_icp_text

SERVICE_LINES: tuple[ServiceLine, ...] = ("exec_search", "fractional_cxo", "capital_advisory")

SERVICE_LINE_LABELS: dict[str, str] = {
    "exec_search": "Executive search",
    "fractional_cxo": "Fractional CXO",
    "capital_advisory": "Capital advisory",
}

_ALIASES: dict[str, ServiceLine] = {
    "exec_search": "exec_search",
    "executive_search": "exec_search",
    "exec": "exec_search",
    "search": "exec_search",
    "fractional_cxo": "fractional_cxo",
    "fractional": "fractional_cxo",
    "fractional_cxo_advisory": "fractional_cxo",
    "interim": "fractional_cxo",
    "capital_advisory": "capital_advisory",
    "capital": "capital_advisory",
    "advisory": "capital_advisory",
    "m_and_a": "capital_advisory",
}


def service_line_label(value: str | None) -> str:
    key = (value or "").strip().lower()
    return SERVICE_LINE_LABELS.get(key, key.replace("_", " ").title() or "Auto")


def normalize_service_line(value: str | None, icp_text: str = "") -> ServiceLine:
    """Map LLM output or free text to a supported service line."""
    raw = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in SERVICE_LINES:
        return raw  # type: ignore[return-value]
    if raw in _ALIASES:
        return _ALIASES[raw]
    text = (icp_text or "").lower()
    if any(
        k in text
        for k in (
            "fractional",
            "interim cfo",
            "interim ceo",
            "part-time cfo",
            "part-time ceo",
            "fractional cfo",
            "fractional ceo",
        )
    ):
        return "fractional_cxo"
    if any(
        k in text
        for k in (
            "capital advisory",
            "structured credit",
            "working capital",
            "debt advisory",
            "m&a",
            "mergers",
            "acquisition advisory",
            "fundraise",
            "fund raising",
            "growth capital",
        )
    ):
        return "capital_advisory"
    return "exec_search"


def same_icp_brief(a: str | None, b: str | None) -> bool:
    """True when two briefs are the same ICP (whitespace/case ignored)."""
    return normalize_icp_text(a or "") == normalize_icp_text(b or "")


def brief_changed_from_session(current: str | None, locked: str | None) -> bool:
    """True when the user edited the brief away from the active Fetch-more session."""
    locked = (locked or "").strip()
    if not locked:
        return False
    return not same_icp_brief(current, locked)

