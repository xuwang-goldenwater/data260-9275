"""Model adapter.

Required exact path: src/model_client.py

Provides one interface over whichever LLM provider is configured, so the rest
of the application never imports a vendor SDK directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelResponse:
    """Normalized response returned by every provider."""

    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


class ModelClient:
    """Uniform chat interface over a configured provider.

    TODO: implement per the Homework 1 instructions.
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.provider = provider or os.getenv("MODEL_PROVIDER", "anthropic")
        self.model = model or os.getenv("MODEL_NAME", "claude-sonnet-4-5")
        self.api_key = api_key or os.getenv(
            f"{self.provider.upper()}_API_KEY", ""
        )

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> ModelResponse:
        """Send a single prompt and return a normalized response."""
        raise NotImplementedError("TODO: implement in Homework 1")


__all__ = ["ModelClient", "ModelResponse"]
