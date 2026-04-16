import time
from typing import Any

import httpx

from src.infrastructure.llms.providers import (
    LLMProvider,
)
from src.domain.llm import LLMRequest, LLMResponse
from src.core.logger import get_logger
from src.core.config import LLM_PROVIDERS


logger = get_logger(__name__)


MODELS = {
    "main":    ("gemini-2.0-flash", False, 2),
}


class GeminiProvider(LLMProvider):
    """
    Provider Gemini via IAStudio.
    Fallback ultime — 1M contexte mais 20 req/jour.
    Réservé aux textes >30k tokens si Groq échoue.
    """

    name = "gemini"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self):
        self._api_key = LLM_PROVIDERS.get("GEMINI")
        if not self._api_key:
            raise ValueError("AISTUDIO_KEY manquante dans la config")

    async def complete(self, request: LLMRequest) -> LLMResponse:
        t0 = time.monotonic()
        url = self.BASE_URL.format(model=request.model)

        # Convertir les messages au format Gemini
        contents = []
        system_prompt = ""
        for m in request.messages:
            if m.role == "system":
                system_prompt = m.content
            else:
                contents.append({
                    "role": "user" if m.role == "user" else "model",
                    "parts": [{"text": m.content}],
                })

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
            },
        }
        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        try:
            async with httpx.AsyncClient(timeout=request.timeout) as client:
                resp = await client.post(
                    url,
                    params={"key": self._api_key},
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()

            content = data["candidates"][0]["content"]["parts"][0]["text"]
            usage   = data.get("usageMetadata", {})
            return LLMResponse(
                content           = content,
                provider          = self.name,
                model             = request.model,
                prompt_tokens     = usage.get("promptTokenCount", 0),
                completion_tokens = usage.get("candidatesTokenCount", 0),
                latency_ms        = int((time.monotonic() - t0) * 1000),
                success           = True,
            )

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            logger.warning(f"Gemini HTTP {status} : {e.response.text[:200]}")
            return self._error_response(f"HTTP {status}")

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            logger.warning(f"Gemini timeout/connect : {e}")
            return self._error_response(f"timeout: {e}")

        except Exception as e:
            logger.exception("Gemini erreur inattendue")
            return self._error_response(str(e))
