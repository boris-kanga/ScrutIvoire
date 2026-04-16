import time

import httpx

from src.infrastructure.llms.providers import (
    LLMProvider,
)
from src.domain.llm import LLMRequest, LLMResponse
from src.core.logger import get_logger
from src.core.config import LLM_PROVIDERS


logger = get_logger(__name__)


MODELS = {
    "fast":    ("llama3.1-8b", False, 1),
    "large":   ("qwen-3-235b-a22b-instruct-2507", False, 2),
}


class CerebrasProvider(LLMProvider):
    """
    Provider Cerebras — OpenAI-compatible API.
    Ultra rapide (~2600 tok/s), idéal pour Type B.
    """

    name = "cerebras"
    BASE_URL = "https://api.cerebras.ai/v1/chat/completions"

    def __init__(self):
        self._api_key = LLM_PROVIDERS.get("CEREBRAS")
        if not self._api_key:
            raise ValueError("CEREBRAS_KEY manquante dans la config")

    async def complete(self, request: LLMRequest) -> LLMResponse:
        t0 = time.monotonic()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type":  "application/json",
        }
        body = {
            "model":       request.model,
            "messages":    [{"role": m.role, "content": m.content}
                            for m in request.messages],
            "temperature": request.temperature,
            "max_tokens":  request.max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=request.timeout) as client:
                resp = await client.post(self.BASE_URL, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()

            content = data["choices"][0]["message"]["content"]
            usage   = data.get("usage", {})
            return LLMResponse(
                content           = content,
                provider          = self.name,
                model             = request.model,
                prompt_tokens     = usage.get("prompt_tokens", 0),
                completion_tokens = usage.get("completion_tokens", 0),
                latency_ms        = int((time.monotonic() - t0) * 1000),
                success           = True,
            )

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            logger.warning(f"Cerebras HTTP {status} : {e.response.text[:200]}")
            return self._error_response(f"HTTP {status}")

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            logger.warning(f"Cerebras timeout/connect : {e}")
            return self._error_response(f"timeout: {e}")

        except Exception as e:
            logger.exception("Cerebras erreur inattendue")
            return self._error_response(str(e))
