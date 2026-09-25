"""Claude Opus 5.5 on Microsoft Foundry (Azure): one structured-JSON call with retries.

Notes on the model (verified against the current API docs):
- Opus 5.5 rejects `temperature` (HTTP 400); precision comes from `effort` and the prompts.
- Thinking is always on (adaptive); `output_config.effort` controls its depth.
- `output_config.format` (JSON schema) guarantees the text block is valid JSON.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Protocol

import anthropic
from anthropic import AnthropicFoundry
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

log = logging.getLogger(__name__)

RETRYABLE = (
    anthropic.RateLimitError,        # 429 — Azure TPM/RPM throttling
    anthropic.APIConnectionError,    # includes APITimeoutError
    anthropic.InternalServerError,   # 500
    anthropic.ServiceUnavailableError,
    anthropic.OverloadedError,       # 529
)


class RefusalError(RuntimeError):
    """The model declined the request (stop_reason == "refusal")."""


class OutputTruncatedError(RuntimeError):
    """The answer hit max_tokens before finishing."""


@dataclass
class LLMResult:
    data: dict
    usage: dict = field(default_factory=dict)


class LLM(Protocol):
    def complete_json(self, *, system: list[dict], user: str, schema: dict,
                      effort: str, max_tokens: int) -> LLMResult: ...


class FoundryLLM:
    def __init__(self, model: str, timeout: float = 1800.0):
        # SDK retries are disabled: tenacity owns retrying so backoff is not doubled.
        self.client = AnthropicFoundry(max_retries=0, timeout=timeout)
        self.model = model

    @retry(
        retry=retry_if_exception_type(RETRYABLE),
        wait=wait_random_exponential(multiplier=2, min=5, max=180),
        stop=stop_after_attempt(8),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
    def complete_json(self, *, system: list[dict], user: str, schema: dict,
                      effort: str, max_tokens: int) -> LLMResult:
        with self.client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        ) as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            raise RefusalError(f"model declined the request: {details}")
        if message.stop_reason == "max_tokens":
            raise OutputTruncatedError(f"answer exceeded max_tokens={max_tokens}")

        text = next(block.text for block in message.content if block.type == "text")
        u = message.usage
        usage = {
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,
            "cache_read_input_tokens": u.cache_read_input_tokens or 0,
            "cache_creation_input_tokens": u.cache_creation_input_tokens or 0,
        }
        log.info("call: in=%d cache_read=%d cache_write=%d out=%d", usage["input_tokens"],
                 usage["cache_read_input_tokens"], usage["cache_creation_input_tokens"],
                 usage["output_tokens"])
        return LLMResult(data=json.loads(text), usage=usage)
