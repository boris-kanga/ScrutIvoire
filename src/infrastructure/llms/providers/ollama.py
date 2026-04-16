import time

import httpx

from src.infrastructure.llms.providers import (
    LLMProvider,
)
from src.domain.llm import LLMRequest, LLMResponse
from src.core.logger import get_logger
from src.core.config import OLLAMA_URL


logger = get_logger(__name__)

MODELS = {
    "fast": ("llama3.1:latest", False, float("inf")),
    "large": ("llama3.1:latest", False, float("inf")),
    "main": ("qwen3:14b-q4_K_M", False, float("inf")),
}



class OllamaProvider(LLMProvider):
    """
    Provider Ollama local — fallback ultime sans quota.
    """

    name = "ollama"

    def __init__(self):
        if OLLAMA_URL is None:
            raise ValueError("OLLAMA_URL needed")
        self._base_url = f"{OLLAMA_URL}/api/chat"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        t0 = time.monotonic()

        messages = [{"role": m.role, "content": m.content}
                    for m in request.messages]

        # Mode nothink pour les tâches rapides (Type B)
        # Mode think pour les analyses complexes (Type A)
        if not request.think:
            # Ajouter /nothink au contenu du dernier message user
            for msg in reversed(messages):
                if msg["role"] == "user":
                    msg["content"] = "/nothink\n" + msg["content"]
                    break

        body = {
            "model":    request.model,
            "messages": messages,
            "stream":   False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
                "num_ctx":     32768,
            },
            **({
             "format": request.response_format
            } if request.response_format else {}),
        }

        try:
            async with httpx.AsyncClient(timeout=request.timeout) as client:
                resp = await client.post(self._base_url, json=body)
                resp.raise_for_status()
                data = resp.json()

            content = data["message"]["content"]

            # Retirer le bloc <think>...</think> si présent
            if "<think>" in content and "</think>" in content:
                end = content.find("</think>") + len("</think>")
                content = content[end:].strip()

            usage = data.get("usage", {})
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
            logger.warning(f"Ollama HTTP {status} : {e.response.text[:200]}")
            return self._error_response(f"HTTP {status}")

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            logger.warning(f"Ollama timeout/connect : {e}")
            return self._error_response(f"timeout: {e}")

        except Exception as e:
            logger.exception("Ollama erreur inattendue")
            return self._error_response(str(e))