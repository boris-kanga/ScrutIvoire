import time
from typing import AsyncGenerator

import httpx

from src.infrastructure.llms.providers import LLMProvider
from src.infrastructure.llms.providers._mixin import OpenAICompatibleMixin
from src.domain.llm import LLMRequest, LLMResponse, LLMStreamChunk
from src.core.logger import get_logger
from src.core.config import LLM_PROVIDERS


logger = get_logger(__name__)


# Modèles disponibles — ajuste les priorités selon ton usage
MODELS = {
    "main":  ("gpt-4o-mini", False, 1),
    "large": ("gpt-4o",      False, 1),
    "fast":  ("gpt-4o-mini", False, 1),
}


class OpenAIProvider(OpenAICompatibleMixin, LLMProvider):
    """
    Provider OpenAI — API officielle.
    Compatible tool calling, streaming, response_format (json_object / json_schema).
    Hérite du mixin OpenAI-compatible — aucune logique dupliquée.
    """

    name = "openai"
    BASE_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self):
        self._api_key = LLM_PROVIDERS.get("OPENAI")
        if not self._api_key:
            raise ValueError("OPENAI_KEY manquante dans la config")

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
            body_text = e.response.text[:300]
            logger.warning(f"OpenAI HTTP {status} : {body_text}")
            # Détail de l'erreur OpenAI (quota, clé invalide, etc.)
            try:
                detail = e.response.json().get("error", {}).get("message", "")
            except Exception:
                detail = body_text
            return self._error_response(f"HTTP {status}: {detail}")

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            logger.warning(f"OpenAI timeout/connect : {e}")
            return self._error_response(f"timeout: {e}")

        except Exception as e:
            logger.exception("OpenAI erreur inattendue")
            return self._error_response(str(e))

    async def stream(self, request: LLMRequest) -> AsyncGenerator[LLMStreamChunk, None]:
        """Streaming SSE — async for chunk in provider.stream(request)."""
        request.stream = True
        async for chunk in self._stream(request):
            yield chunk