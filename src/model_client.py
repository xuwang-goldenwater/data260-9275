"""
Reusable model adapter for DATA 260.

Every model call in this repository goes through ModelClient.complete().
Swapping the backend (a different local model, or a hosted API) means editing
this file only; no caller changes.

The Ollama Python client is used directly rather than a framework wrapper
because its response carries prompt_eval_count and eval_count, which are the
per-turn input and output token counts that Homework 1 Part 4 must report.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import ollama

DEFAULT_MODEL = "qwen3:8b"


@dataclass
class ModelResponse:
    """One model turn and its accounting."""

    text: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: float
    model: str
    raw: Dict[str, Any] = field(default_factory=dict)


class ModelClient:
    """Stable interface over a chat model.

    The only method callers need is complete(messages, tools=None).
    Cumulative counters are kept so a CLI can print running totals.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.0,
        host: Optional[str] = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self._client = ollama.Client(host=host) if host else ollama.Client()

        # cumulative accounting across the life of this client
        self.turn_count = 0
        self.cumulative_input_tokens = 0
        self.cumulative_output_tokens = 0

    # -- main interface ----------------------------------------------------

    def complete(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        response_format: Optional[Any] = None,
        think: bool = False,
    ) -> ModelResponse:
        """Send a chat conversation and return the model's reply.

        messages         list of {"role": "system"|"user"|"assistant", "content": str}
        tools            reserved for later homeworks; accepted and forwarded
        temperature      overrides the client default for this call only
        response_format  Ollama `format` value: "json" or a JSON schema dict
        think            qwen3 and other reasoning models emit a thinking block
                         unless this is turned off; off by default so the reply
                         is the answer itself
        """
        temp = self.temperature if temperature is None else temperature

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "options": {"temperature": temp},
        }
        if tools:
            kwargs["tools"] = tools
        if response_format is not None:
            kwargs["format"] = response_format

        started = time.perf_counter()
        try:
            response = self._client.chat(think=think, **kwargs)
        except TypeError:
            # older ollama clients do not accept think=
            response = self._client.chat(**kwargs)
        latency_ms = (time.perf_counter() - started) * 1000.0

        payload = dict(response)
        text = (payload.get("message") or {}).get("content", "") or ""

        input_tokens = int(payload.get("prompt_eval_count") or 0)
        output_tokens = int(payload.get("eval_count") or 0)

        self.turn_count += 1
        self.cumulative_input_tokens += input_tokens
        self.cumulative_output_tokens += output_tokens

        return ModelResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            latency_ms=latency_ms,
            model=self.model,
            raw=payload,
        )

    # -- accounting helpers ------------------------------------------------

    def stats(self) -> Dict[str, int]:
        """Cumulative counters. Does not alter any conversation state."""
        return {
            "turn_count": self.turn_count,
            "cumulative_input_tokens": self.cumulative_input_tokens,
            "cumulative_output_tokens": self.cumulative_output_tokens,
            "cumulative_total_tokens": self.cumulative_input_tokens
            + self.cumulative_output_tokens,
        }

    def reset_stats(self) -> None:
        self.turn_count = 0
        self.cumulative_input_tokens = 0
        self.cumulative_output_tokens = 0
