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
    "fast":  ("llama3.1-8b", False, 3),
    "large": ("qwen-3-235b-a22b-instruct-2507", False, 2),
}


class CerebrasProvider(OpenAICompatibleMixin, LLMProvider):
    """
    Provider Cerebras — OpenAI-compatible API.
    Ultra rapide (~2600 tok/s), idéal pour Type B.
    Supporte le tool calling et le streaming.
    Note : response_format non supporté (modèles llama Cerebras l'ignorent).
    """

    name = "cerebras"
    BASE_URL = "https://api.cerebras.ai/v1/chat/completions"
    supports_response_format: bool = False  # ignoré par les modèles Cerebras

    def __init__(self):
        self._api_key = LLM_PROVIDERS.get("CEREBRAS")
        if not self._api_key:
            raise ValueError("CEREBRAS_KEY manquante dans la config")

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
            logger.warning(f"Cerebras HTTP {status} : {e.response.text[:200]}")
            return self._error_response(f"HTTP {status}")

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            logger.warning(f"Cerebras timeout/connect : {e}")
            return self._error_response(f"timeout: {e}")

        except Exception as e:
            logger.exception("Cerebras erreur inattendue")
            return self._error_response(str(e))

    async def stream(self, request: LLMRequest) -> AsyncGenerator[LLMStreamChunk, None]:
        """Streaming SSE — async for chunk in provider.stream(request)."""
        request.stream = True
        async for chunk in self._stream(request):
            yield chunk