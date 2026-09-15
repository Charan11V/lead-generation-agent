"""White-label display name. Default remains Frequency (primary VPS).

Set on the Tovyq sidecar only:
  APP_BRAND=Tovyq
  APP_BRAND_DOMAIN=tovyq.swameda.com
  APP_BRAND_URL=https://tovyq.swameda.com
"""

from __future__ import annotations

import os

DEFAULT_BRAND = "Frequency"
DEFAULT_DOMAIN = "frequency.cx"
DEFAULT_URL = "https://frequency.cx"


def brand_name() -> str:
    return (os.getenv("APP_BRAND") or DEFAULT_BRAND).strip() or DEFAULT_BRAND


def brand_wordmark() -> str:
    return brand_name().upper()


def brand_domain() -> str:
    return (os.getenv("APP_BRAND_DOMAIN") or DEFAULT_DOMAIN).strip() or DEFAULT_DOMAIN


def brand_url() -> str:
    explicit = (os.getenv("APP_BRAND_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    domain = brand_domain()
    if domain.startswith("http://") or domain.startswith("https://"):
        return domain.rstrip("/")
    return f"https://{domain}"


def rewrite_frequency(text: str) -> str:
    """Swap Frequency wording when a white-label brand is set."""
    name = brand_name()
    if name.lower() == DEFAULT_BRAND.lower() or not text:
        return text
    return (
        text.replace("https://frequency.cx", brand_url())
        .replace("frequency.cx", brand_domain())
        .replace("Frequency", name)
        .replace("FREQUENCY", name.upper())
    )
