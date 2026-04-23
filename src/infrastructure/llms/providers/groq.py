import time
from typing import AsyncGenerator

import httpx

from src.infrastructure.llms.providers import LLMProvider
from src.infrastructure.llms.providers._mixin import OpenAICompatibleMixin
from src.domain.llm import LLMRequest, LLMResponse, LLMStreamChunk
from src.core.logger import get_logger
from src.core.config import LLM_PROVIDERS


logger = get_logger(__name__)


MODELS = {
    "fast":  ("llama-3.1-8b-instant", False, 2),
    "main":  ("meta-llama/llama-4-scout-17b-16e-instruct", False, 1),
    "large": ("meta-llama/llama-4-scout-17b-16e-instruct", False, 1),
}


class GroqProvider(OpenAICompatibleMixin, LLMProvider):
    """
    Provider Groq — OpenAI-compatible API.
    1M contexte, idéal pour Type A (analyses textuelles).
    Supporte le tool calling et le streaming.
    """

    name = "groq"
    BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self):
        self._api_key = LLM_PROVIDERS.get("GROQ")
        if not self._api_key:
            raise ValueError("GROQ_KEY manquante dans la config")

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if request.stream:
            raise ValueError(
                "Utilisez stream() pour le streaming, pas complete()"
            )

        t0 = time.monotonic()
        body = self._build_body(request)

        try:
            async with httpx.AsyncClient(timeout=request.timeout) as client:
                resp = await client.post(
                    self.BASE_URL, headers=self._headers(), json=body
                )
                resp.raise_for_status()
                data = resp.json()

            return self._parse_response(data, request, t0)

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            logger.warning(f"Groq HTTP {status} : {e.response.text[:200]}")
            return self._error_response(f"HTTP {status}")

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            logger.warning(f"Groq timeout/connect : {e}")
            return self._error_response(f"timeout: {e}")

        except Exception as e:
            logger.exception("Groq erreur inattendue")
            return self._error_response(str(e))

    async def stream(self, request: LLMRequest) -> AsyncGenerator[LLMStreamChunk, None]:
        """Streaming SSE — async for chunk in provider.stream(request)."""
        request.stream = True
        async for chunk in self._stream(request):
            yield chunk