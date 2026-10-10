"""Map provider and transport exceptions to the application's stable LLM error categories.

LangChain wraps the provider SDK's errors (for Gemini the HTTP code lives on the wrapped
``__cause__``), and the Ollama client raises ``httpx`` errors directly, so classification walks the
exception chain. Provider text is read only to classify and is never copied into the result:
messages can echo request details, and nothing here may carry a key, a prompt, or a question.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

# Fragments that identify a rejected credential. Google reports a bad API key as HTTP 400
# INVALID_ARGUMENT rather than 401, so the status code alone is not enough.
_CREDENTIAL_MARKERS = (
    "api key not valid",
    "api_key_invalid",
    "invalid api key",
    "unauthenticated",
    "permission_denied",
    "permission denied",
)
_RATE_LIMIT_MARKERS = ("resource_exhausted", "rate limit", "quota")
_MAX_CHAIN_DEPTH = 6


@dataclass(frozen=True)
class ClassifiedError:
    code: str
    message: str
    status_code: int
    # Only transient infrastructure failures are worth another attempt. Rate limits, timeouts,
    # credential and model errors are not, and validation failures never reach this module.
    retryable: bool = False


def _chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(chain) < _MAX_CHAIN_DEPTH:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return chain


def _status_codes(chain: list[BaseException]) -> set[int]:
    codes: set[int] = set()
    for error in chain:
        for attribute in ("code", "status_code", "status"):
            value = getattr(error, attribute, None)
            if isinstance(value, int) and 100 <= value <= 599:
                codes.add(value)
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            codes.add(status)
    return codes


def classify_provider_error(error: BaseException, label: str) -> ClassifiedError:
    """Classify ``error`` raised while calling the model provider named ``label``."""
    chain = _chain(error)
    codes = _status_codes(chain)
    text = " ".join(str(item) for item in chain).casefold()
    names = " ".join(type(item).__name__ for item in chain).casefold()

    if (
        any(isinstance(item, (TimeoutError, httpx.TimeoutException)) for item in chain)
        or "timeout" in names
        or codes & {408, 504}
    ):
        return ClassifiedError(
            "LLM_TIMEOUT", f"The {label} request exceeded its configured timeout.", 504
        )
    if 429 in codes or any(marker in text for marker in _RATE_LIMIT_MARKERS):
        return ClassifiedError(
            "LLM_RATE_LIMITED", f"The configured {label} provider is temporarily rate limited.", 503
        )
    if codes & {401, 403} or any(marker in text for marker in _CREDENTIAL_MARKERS):
        return ClassifiedError(
            "LLM_CREDENTIALS_INVALID",
            f"The credentials for the {label} provider were rejected.",
            503,
        )
    if 404 in codes:
        return ClassifiedError(
            "LLM_MODEL_UNAVAILABLE", f"The configured {label} model is unavailable.", 503
        )
    if (
        any(code >= 500 for code in codes)
        or any(isinstance(item, (httpx.TransportError, ConnectionError, OSError)) for item in chain)
        or "connect" in names
    ):
        return ClassifiedError(
            "LLM_PROVIDER_UNAVAILABLE",
            f"The {label} provider is unavailable.",
            503,
            retryable=True,
        )
    return ClassifiedError(
        "LLM_PROVIDER_ERROR", f"The configured {label} provider could not generate SQL.", 502
    )
