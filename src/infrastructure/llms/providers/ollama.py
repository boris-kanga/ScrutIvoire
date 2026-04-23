import json
import time
from typing import AsyncGenerator

import httpx

from src.infrastructure.llms.providers import LLMProvider
from src.infrastructure.llms.providers._mixin import (
    _serialize_messages,
)
from src.domain.llm import LLMRequest, LLMResponse, LLMStreamChunk, LLMToolCall
from src.core.logger import get_logger
from src.core.config import OLLAMA_URL


logger = get_logger(__name__)


MODELS = {
    "fast":  ("llama3.1:latest", False, float("inf")),
    "large": ("llama3.1:latest", False, float("inf")),
    "main":  ("qwen3:14b-q4_K_M", False, float("inf")),
}


class OllamaProvider(LLMProvider):
    """
    Provider Ollama local — fallback ultime sans quota.
    Utilise l'API /api/chat (format OpenAI-like natif d'Ollama).
    Supporte le tool calling et le streaming.

    Note : Ollama utilise son propre endpoint /api/chat, pas /v1/chat/completions,
    mais le format des tools est identique au format OpenAI.
    """

    name = "ollama"

    def __init__(self):
        if OLLAMA_URL is None:
            raise ValueError("OLLAMA_URL needed")
        self._base_url = f"{OLLAMA_URL}/api/chat"

    # ------------------------------------------------------------------ #
    #  Construction du body                                                #
    # ------------------------------------------------------------------ #

    def _build_body(self, request: LLMRequest, stream: bool = False) -> dict:
        messages = _serialize_messages(request)

        # Mode nothink pour les tâches rapides
        if not request.think:
            for msg in reversed(messages):
                if msg["role"] == "user":
                    msg["content"] = "/nothink\n" + msg["content"]
                    break

        body: dict = {
            "model":    request.model,
            "messages": messages,
            "stream":   stream,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
                "num_ctx":     32768,
            },
        }

        # Ollama utilise "format": "json" et non response_format OpenAI
        if request.response_format == "json":
            body["format"] = "json"

        # Ollama supporte les tools au format OpenAI
        if request.tools:
            body["tools"] = request.tools

        return body

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _strip_think(content: str) -> str:
        if "<think>" in content and "</think>" in content:
            end = content.find("</think>") + len("</think>")
            return content[end:].strip()
        return content

    @staticmethod
    def _parse_tool_calls(raw: list[dict]) -> list[LLMToolCall]:
        result = []
        for tc in raw:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            result.append(LLMToolCall(
                id=tc.get("id", ""),
                name=fn.get("name", ""),
                arguments=args,
            ))
        return result

    # ------------------------------------------------------------------ #
    #  complete()                                                          #
    # ------------------------------------------------------------------ #

    async def complete(self, request: LLMRequest) -> LLMResponse:
        t0 = time.monotonic()
        body = self._build_body(request, stream=False)

        try:
            async with httpx.AsyncClient(timeout=request.timeout) as client:
                resp = await client.post(self._base_url, json=body)
                resp.raise_for_status()
                data = resp.json()

            message = data["message"]
            content = self._strip_think(message.get("content") or "")

            raw_tool_calls = message.get("tool_calls")
            tool_calls = self._parse_tool_calls(raw_tool_calls) if raw_tool_calls else None

            usage = data.get("usage", {})
            return LLMResponse(
                content=content or None,
                tool_calls=tool_calls,
                provider=self.name,
                model=request.model,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                latency_ms=int((time.monotonic() - t0) * 1000),
                success=True,
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

    # ------------------------------------------------------------------ #
    #  stream()                                                            #
    # ------------------------------------------------------------------ #

    async def stream(self, request: LLMRequest) -> AsyncGenerator[LLMStreamChunk, None]:
        """
        Streaming Ollama — chaque ligne est un objet JSON complet (pas SSE).

        async for chunk in provider.stream(request):
            ...
        """
        t0 = time.monotonic()
        body = self._build_body(request, stream=True)

        # Accumulation des tool_calls (Ollama les envoie d'un coup sur le dernier chunk)
        tool_call_acc: list[dict] = []
        prompt_tokens = 0
        completion_tokens = 0

        try:
            async with httpx.AsyncClient(timeout=request.timeout) as client:
                async with client.stream("POST", self._base_url, json=body) as resp:
                    resp.raise_for_status()

                    async for raw_line in resp.aiter_lines():
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue

                        try:
                            data = json.loads(raw_line)
                        except json.JSONDecodeError:
                            continue

                        message = data.get("message", {})
                        done = data.get("done", False)

                        # Tokens (présents sur le dernier chunk)
                        if done:
                            prompt_tokens = data.get("prompt_eval_count", 0)
                            completion_tokens = data.get("eval_count", 0)

                        # Fragment texte
                        content = message.get("content", "")
                        if content:
                            content = self._strip_think(content)
                            if content:
                                yield LLMStreamChunk(delta=content)

                        # Tool calls (Ollama les envoie entiers sur le dernier chunk)
                        raw_tcs = message.get("tool_calls")
                        if raw_tcs:
                            for tc in self._parse_tool_calls(raw_tcs):
                                yield LLMStreamChunk(tool_call=tc)

                        if done:
                            break

            yield LLMStreamChunk(
                done=True,
                provider=self.name,
                model=request.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=int((time.monotonic() - t0) * 1000),
                success=True,
            )

        except httpx.HTTPStatusError as e:
            yield LLMStreamChunk(
                done=True, success=False,
                error=f"HTTP {e.response.status_code}",
                provider=self.name, model=request.model,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            yield LLMStreamChunk(
                done=True, success=False,
                error=f"timeout: {e}",
                provider=self.name, model=request.model,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        except Exception as e:
            logger.exception("Ollama stream erreur inattendue")
            yield LLMStreamChunk(
                done=True, success=False,
                error=str(e),
                provider=self.name, model=request.model,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )