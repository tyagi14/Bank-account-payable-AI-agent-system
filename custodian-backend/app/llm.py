"""Every LLM call goes through the LiteLLM gateway with the calling agent's own virtual key, returns a
schema-validated object via Instructor (with retries), and is wrapped in a GenAI-convention span."""
import asyncio
import re
from typing import TypeVar

import instructor
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.telemetry import tracer

T = TypeVar("T", bound=BaseModel)

# Gateway route -> provider behind it (for gen_ai.system); agent code never names a provider model.
ROUTES = {"custodian-reasoning": "openai", "custodian-routine": "groq", "custodian-guardrail": "groq"}
_clients: dict[str, instructor.AsyncInstructor] = {}
TOOL_FORMAT_ATTEMPTS = 3
TRANSIENT_ATTEMPTS = 8
MAX_BACKOFF_SECONDS = 60.0
_RETRY_AFTER = re.compile(r"try again in (?:(\d+)m)?([\d.]+)s")


def _transient_delay(exc: Exception, attempt: int) -> float | None:
    """Seconds to wait before retrying a provider throttle or a gateway blip; None if not transient.
    Quota exhaustion (e.g. "no credits") is a 429 too, but carries no retry hint and is not retried."""
    text = str(exc)
    match = _RETRY_AFTER.search(text)
    if match and "rate_limit_exceeded" in text:
        wait = int(match.group(1) or 0) * 60 + float(match.group(2)) + 0.5
        return wait if wait <= MAX_BACKOFF_SECONDS else None  # a daily cap is not worth waiting out inline
    if "Error code: 503" in text or "no_db_connection" in text:
        return min(2.0 ** attempt, MAX_BACKOFF_SECONDS)
    return None


def _client(base_url: str, key: str) -> instructor.AsyncInstructor:
    if key not in _clients:
        _clients[key] = instructor.from_openai(AsyncOpenAI(base_url=base_url, api_key=key, max_retries=0, timeout=180),
                                               mode=instructor.Mode.TOOLS)
    return _clients[key]


async def structured(*, base_url: str, key: str, agent: str, route: str, response_model: type[T], system: str, user: str,
                     max_retries: int = 3) -> tuple[T, dict]:
    if not key:
        raise RuntimeError(f"no LiteLLM virtual key configured for agent {agent}")
    with tracer.start_as_current_span(f"chat {route}") as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.system", ROUTES[route])
        span.set_attribute("gen_ai.request.model", route)
        span.set_attribute("gen_ai.agent.name", agent)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        format_failures = 0
        for attempt in range(TRANSIENT_ATTEMPTS):
            try:
                result, completion = await _client(base_url, key).chat.completions.create_with_completion(
                    model=route, response_model=response_model, max_retries=max_retries, messages=messages)
                break
            except Exception as exc:  # Instructor wraps provider errors, so classify by content, not type
                if "tool_use_failed" in str(exc):
                    # Groq rejects a generation that skipped or malformed the tool call (gpt-oss models
                    # do this intermittently). Retried a bounded number of times, then surfaced.
                    format_failures += 1
                    if format_failures == TOOL_FORMAT_ATTEMPTS:
                        raise
                    span.add_event("tool_call_format_retry", {"attempt": format_failures})
                    await asyncio.sleep(0.5 * format_failures)
                    continue
                delay = _transient_delay(exc, attempt)
                if delay is None or attempt == TRANSIENT_ATTEMPTS - 1:
                    raise
                span.add_event("transient_retry", {"attempt": attempt + 1, "delay_seconds": delay})
                await asyncio.sleep(delay)
        else:
            raise RuntimeError(f"{route}: no valid response after {TRANSIENT_ATTEMPTS} attempts")
        usage = completion.usage
        span.set_attribute("gen_ai.response.model", completion.model)
        span.set_attribute("gen_ai.usage.input_tokens", usage.prompt_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", usage.completion_tokens)
        return result, {"route": route, "provider": ROUTES[route], "response_model": completion.model,
                        "input_tokens": usage.prompt_tokens, "output_tokens": usage.completion_tokens}
