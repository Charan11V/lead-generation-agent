from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


EXTRACT_MODEL_DEFAULT = "gpt-4o-mini"
DRAFT_MODEL_DEFAULT = "gpt-4o"


class LLM:
    def __init__(
        self,
        api_key: str,
        extract_model: str = EXTRACT_MODEL_DEFAULT,
        draft_model: str = DRAFT_MODEL_DEFAULT,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required.")
        self.client = OpenAI(api_key=api_key)
        self.extract_model = extract_model
        self.draft_model = draft_model

    def parse(
        self,
        messages: list[dict],
        response_format: type[T],
        *,
        model: str | None = None,
        temperature: float = 0,
    ) -> T:
        chosen = model or self.extract_model
        last_err: Exception | None = None
        parsers = []
        if hasattr(self.client.chat.completions, "parse"):
            parsers.append(self.client.chat.completions.parse)
        if hasattr(self.client, "beta") and hasattr(self.client.beta.chat.completions, "parse"):
            parsers.append(self.client.beta.chat.completions.parse)
        for parser in parsers:
            try:
                result = parser(
                    model=chosen,
                    messages=messages,
                    response_format=response_format,
                )
                parsed = result.choices[0].message.parsed
                if parsed is None:
                    raise ValueError("Empty parsed response")
                return parsed
            except Exception as exc:
                last_err = exc
        fallback_messages = messages + [
            {
                "role": "system",
                "content": (
                    "Return ONLY valid JSON matching this schema:\n"
                    + json.dumps(response_format.model_json_schema())
                ),
            }
        ]
        try:
            raw = self.client.chat.completions.create(
                model=chosen,
                messages=fallback_messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            content = raw.choices[0].message.content or "{}"
            return response_format.model_validate_json(content)
        except Exception as exc:
            raise RuntimeError(f"LLM parse failed: {last_err or exc}") from exc

    def text(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.4,
    ) -> str:
        chosen = model or self.draft_model
        result = self.client.chat.completions.create(
            model=chosen,
            messages=messages,
            temperature=temperature,
        )
        return (result.choices[0].message.content or "").strip()


def load_json(name: str) -> dict | list:
    path = Path(__file__).resolve().parent.parent / "data" / name
    return json.loads(path.read_text(encoding="utf-8"))
