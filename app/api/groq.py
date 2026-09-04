"""A thin client for Groq's OpenAI-compatible chat endpoint (ADR-026).

One function. The model is asked for a JSON object and nothing else; what
it says is returned verbatim with the usage counters and the wall-clock
latency, and the caller - sim.py - decides what, if anything, to do with
it. This module never sees an account id, an amount, or an order.
"""

from __future__ import annotations

import time

import httpx

from config import settings


class GroqError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def configured() -> bool:
    return bool(settings.groq_api_key.strip())


def complete(
    system: str,
    user: str,
    *,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1500,
) -> dict:
    """One chat completion in JSON mode.

    Returns {"content", "reasoning", "model", "prompt_tokens",
    "completion_tokens", "reasoning_tokens", "latency_ms"}. Raises GroqError
    with the HTTP status on refusal - 429 is the free tier's rate limit and
    the caller records it as such.

    The gpt-oss models think before they answer, and those thinking tokens
    count against `max_tokens`: a 400-token budget left the JSON cut off
    and Groq answered 400 "failed to validate JSON" (2026-09-04). So the
    budget is generous and the effort is set low - a trade intent does not
    need a long deliberation, and the deliberation is kept as data anyway.
    """
    if not configured():
        raise GroqError("GROQ_API_KEY is not set")
    chosen = model or settings.groq_model
    body = {
        "model": chosen,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        # Only the reasoning models accept this; others reject unknown fields.
        **({"reasoning_effort": "low"} if "gpt-oss" in chosen else {}),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    headers = {
        "authorization": f"Bearer {settings.groq_api_key.strip()}",
        "content-type": "application/json",
    }
    started = time.monotonic()
    try:
        with httpx.Client(timeout=settings.http_timeout_seconds) as client:
            response = client.post(
                settings.groq_base_url.rstrip("/") + "/chat/completions",
                json=body,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise GroqError(f"groq unreachable: {exc}") from exc
    latency_ms = int((time.monotonic() - started) * 1000)
    if response.status_code != 200:
        detail = response.text[:300]
        raise GroqError(f"groq HTTP {response.status_code}: {detail}", response.status_code)
    payload = response.json()
    try:
        message = payload["choices"][0]["message"]
        content = message["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GroqError("groq answer had no message content") from exc
    usage = payload.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    reasoning = message.get("reasoning")
    return {
        "content": str(content),
        "reasoning": str(reasoning) if reasoning else None,
        "model": str(payload.get("model") or chosen),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
        "latency_ms": latency_ms,
    }
