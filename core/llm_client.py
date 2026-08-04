"""
Thin LLM client wrapper — Azure OpenAI only, on purpose.

No fallback to another provider if Azure isn't configured, and no
exception-swallowing anywhere in this file: a missing credential or a
failed API call raises immediately. A previous version of this file
tried Azure AI Foundry's endpoint style and then Anthropic as
fallbacks if the primary Azure path wasn't configured — that's gone.
This project has exactly one real credential (a classic Azure OpenAI
resource), so there's exactly one code path, and if it's missing or
broken you'll see a real error, not a silent switch to something else
or a placeholder result.

REASONING MODELS (gpt-5*, o1/o3/o4 series) NEED DIFFERENT PARAMETERS —
this is not optional, Azure rejects the wrong ones outright:
  - `max_tokens` is rejected ("Unsupported parameter: 'max_tokens' is
    not supported with this model. Use 'max_completion_tokens' instead.")
  - `temperature` is also rejected — no custom value accepted.
  - They spend hidden "reasoning tokens" before writing visible output,
    which count against your token budget but never show up as content.
    `reasoning_effort="low"` keeps that spend down for what is
    fundamentally a templated content-generation task.
`_is_reasoning_model()` below is a name-pattern heuristic — if your
deployment name doesn't obviously contain "gpt-5" or match o1/o3/o4,
check this function if things behave unexpectedly.

If the response comes back with no visible content (all of
max_completion_tokens spent on hidden reasoning, nothing left to
write), that raises too, with a message telling you what to check —
it does not return an empty string and let the rest of the pipeline
quietly treat that as valid HTML.

Env vars (all required, no optional alternates):
    AZURE_OPENAI_API_KEY
    AZURE_OPENAI_ENDPOINT       e.g. https://<resource>.openai.azure.com
    AZURE_OPENAI_API_VERSION    e.g. 2025-01-01 (defaults to 2024-10-21 if unset)
    AZURE_OPENAI_DEPLOYMENT     e.g. gpt-5-mini (defaults to gpt-4o-mini if unset)
"""

from __future__ import annotations

from core.config import settings
from core.logger import get_logger
from core.exceptions import GenerationError
import re
import openai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = get_logger(__name__)


def _is_reasoning_model(deployment_name: str) -> bool:
    n = deployment_name.lower()
    if "gpt-5" in n:
        return True
    if re.match(r"^o[134](-mini|-pro)?$", n):
        return True
    return False


class LLMClient:
    def __init__(self):
        self.provider = "azure"
        self.last_usage = None
        
        endpoint = settings.azure_openai_endpoint
        api_key = settings.azure_openai_api_key

        if endpoint.endswith("/v1") or endpoint.endswith("/v1/"):
            from openai import OpenAI
            self._client = OpenAI(
                api_key=api_key,
                base_url=endpoint,
                default_headers={"api-key": api_key}
            )
        else:
            from openai import AzureOpenAI
            self._client = AzureOpenAI(
                api_key=api_key,
                azure_endpoint=endpoint,
                api_version=settings.azure_openai_api_version,
            )
        self._deployment = settings.azure_openai_deployment
        self._is_reasoning = _is_reasoning_model(self._deployment)
        logger.info(f"Initialized LLMClient with deployment: {self._deployment} (Reasoning: {self._is_reasoning})")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.InternalServerError,
        )),
        reraise=True
    )
    def complete(self, system: str, user: str, max_tokens: int = 4000, images: list[str] | None = None) -> str:
        if images and not self._is_reasoning:
            user_content = [{"type": "text", "text": user}]
            for b64 in images:
                user_content.append({"type": "image_url", "image_url": {"url": b64}})
        else:
            if images and self._is_reasoning:
                logger.warning(f"Images were provided but {self._deployment} is a reasoning model. Images will be ignored.")
            user_content = user

        kwargs: dict = {
            "model": self._deployment,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
        }
        if self._is_reasoning:
            kwargs["max_completion_tokens"] = max_tokens
            kwargs["reasoning_effort"] = "low"
        else:
            kwargs["max_tokens"] = max_tokens
            kwargs["temperature"] = 0.0

        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as e:
            logger.error(f"API call failed: {e}")
            raise GenerationError(f"API call failed: {e}") from e

        content = resp.choices[0].message.content
        if not content:
            finish_reason = resp.choices[0].finish_reason
            logger.error(f"Empty content returned from {self._deployment}. finish_reason={finish_reason}")
            raise GenerationError(
                f"Model '{self._deployment}' returned empty content (finish_reason="
                f"{finish_reason!r}). If this is a reasoning model, it likely spent the "
                f"entire max_completion_tokens budget on hidden reasoning tokens with "
                f"nothing left for visible output — raise max_tokens or check "
                f"usage.completion_tokens_details.reasoning_tokens on the response."
            )

        usage = resp.usage
        usage_dict = {"input_tokens": usage.prompt_tokens, "output_tokens": usage.completion_tokens}
        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None)
        if cached:
            usage_dict["cache_read_input_tokens"] = cached
        reasoning = getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", None)
        if reasoning:
            usage_dict["reasoning_tokens"] = reasoning
        self.last_usage = usage_dict
        
        logger.info(f"LLM Call successful. Tokens: {usage_dict}")
        return content
