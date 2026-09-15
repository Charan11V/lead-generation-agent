"""Structured logging for Docker / ops monitoring of the research pipeline."""

from __future__ import annotations

import json
import logging
import traceback
from typing import Any

_LOGGER = logging.getLogger("frequency_agent")
if not _LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _LOGGER.addHandler(_handler)
    _LOGGER.setLevel(logging.INFO)
    _LOGGER.propagate = False


def configure_logging(level: int = logging.INFO) -> None:
    _LOGGER.setLevel(level)


def _line(
    *,
    event: str,
    run_id: str = "",
    query_id: str = "",
    node: str = "",
    company: str = "",
    error_type: str = "",
    message: str = "",
    **extra: Any,
) -> str:
    payload: dict[str, Any] = {
        "event": event,
        "run_id": run_id or "",
        "query_id": query_id or "",
        "node": node or "",
        "company": company or "",
        "error_type": error_type or "",
        "message": message or "",
    }
    for key, value in extra.items():
        if value is not None and value != "":
            payload[key] = value
    return json.dumps(payload, default=str, ensure_ascii=False)


def log_event(
    event: str,
    *,
    run_id: str = "",
    query_id: str = "",
    node: str = "",
    company: str = "",
    message: str = "",
    level: int = logging.INFO,
    **extra: Any,
) -> None:
    _LOGGER.log(
        level,
        _line(
            event=event,
            run_id=run_id,
            query_id=query_id,
            node=node,
            company=company,
            message=message,
            **extra,
        ),
    )


def log_error(
    *,
    run_id: str = "",
    query_id: str = "",
    node: str = "",
    company: str = "",
    exc: BaseException | None = None,
    message: str = "",
    include_traceback: bool = True,
) -> str:
    """Log a structured error; return a short user-facing reason string."""
    error_type = type(exc).__name__ if exc else "Error"
    short = message or (str(exc).strip() if exc else "unknown error")
    if len(short) > 240:
        short = short[:237] + "..."
    extra: dict[str, Any] = {}
    if include_traceback and exc is not None:
        extra["traceback"] = traceback.format_exc()
    _LOGGER.error(
        _line(
            event="agent_error",
            run_id=run_id,
            query_id=query_id,
            node=node,
            company=company,
            error_type=error_type,
            message=short,
            **extra,
        )
    )
    return f"{error_type}: {short}"


def user_facing_error(exc: BaseException) -> str:
    """Map common failures to short UI copy (no raw pydantic dumps)."""
    name = type(exc).__name__
    text = str(exc) or name

    if name == "ValidationError" or "validation error" in text.lower():
        return (
            "A data validation error stopped this step. "
            "The run may still have partial results — check the log."
        )
    if name in {"AuthenticationError", "PermissionDeniedError"} or "api key" in text.lower():
        return "API authentication failed. Check OpenAI / Tavily keys in Settings or .env."
    if name in {"RateLimitError", "APIConnectionError", "APITimeoutError", "TimeoutException"}:
        return "An upstream API timed out or rate-limited us. Wait a minute and retry."
    if "OPENAI_API_KEY" in text or "api_key" in text.lower() and "required" in text.lower():
        return "OpenAI API key is missing. Add it in .env or Settings."
    if "tavily" in text.lower() and ("credit" in text.lower() or "key" in text.lower()):
        return "Tavily search failed (key or credits). Check Settings or retry later."
    if name in {"JSONDecodeError", "RuntimeError"} and "json" in text.lower():
        return "The model returned invalid JSON. Retry the search."
    if not text.strip():
        return f"Agent failed ({name}). See technical details below."
    if len(text) > 280 or "\n" in text:
        return f"Agent failed ({name}). See technical details below."
    return f"Agent failed: {text}"
