from __future__ import annotations

import json
import time
from typing import Any, AsyncGenerator

import httpx

from src.infrastructure.llms.providers import LLMProvider
from src.domain.llm import LLMRequest, LLMResponse, LLMStreamChunk, LLMToolCall
from src.core.logger import get_logger
from src.core.config import LLM_PROVIDERS


logger = get_logger(__name__)


MODELS = {
    "main": ("gemini-2.0-flash", False, 2),
}


def _openai_tools_to_gemini(tools: list[dict]) -> list[dict]:
    """
    Convertit le format OpenAI function-calling vers le format Gemini.

    OpenAI :
        [{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]

    Gemini :
        [{"functionDeclarations": [{"name": ..., "description": ..., "parameters": ...}]}]
    """
    declarations = []
    for tool in tools:
        if tool.get("type") == "function":
            fn = tool["function"]
            declarations.append({
                "name":        fn["name"],
                "description": fn.get("description", ""),
                "parameters":  fn.get("parameters", {}),
            })
    if not declarations:
        return []
    return [{"functionDeclarations": declarations}]


def _openai_tool_choice_to_gemini(tool_choice: Any) -> dict | None:
    """
    Convertit tool_choice OpenAI → toolConfig Gemini.

    "none"     → NONE
    "auto"     → AUTO
    "required" → ANY
    {"type": "function", "function": {"name": "X"}} → ANY + allowedFunctionNames
    """
    if tool_choice is None:
        return None
    if tool_choice == "none":
        return {"functionCallingConfig": {"mode": "NONE"}}
    if tool_choice == "auto":
        return {"functionCallingConfig": {"mode": "AUTO"}}
    if tool_choice == "required":
        return {"functionCallingConfig": {"mode": "ANY"}}
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        name = tool_choice["function"]["name"]
        return {"functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": [name]}}
    return None


def _build_gemini_messages(request: LLMRequest) -> tuple[list[dict], str]:
    """
    Retourne (contents, system_prompt).
    Gère aussi les messages role='tool' (function response).
    """
    contents = []
    system_prompt = ""

    for m in request.messages:
        if m.role == "system":
            system_prompt = m.content
            continue

        if m.role == "tool":
            # Résultat d'un appel de fonction
            contents.append({
                "role": "user",
                "parts": [{
                    "functionResponse": {
                        "name": m.tool_call_id or "unknown",
                        "response": {"result": m.content},
                    }
                }],
            })
            continue

        if m.role == "assistant":
            parts = []
            # Message assistant avec tool_calls (appels de fonctions)
            if m.tool_calls:
                for tc in m.tool_calls:
                    fn = tc.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        args = {}
                    parts.append({
                        "functionCall": {
                            "name": fn.get("name", ""),
                            "args": args,
                        }
                    })
            if m.content:
                parts.append({"text": m.content})
            if parts:
                contents.append({"role": "model", "parts": parts})
            continue

        # Rôle user
        contents.append({
            "role": "user",
            "parts": [{"text": m.content}],
        })

    return contents, system_prompt


class GeminiProvider(LLMProvider):
    """
    Provider Gemini via AI Studio.
    Supporte le tool calling (functionDeclarations) et le streaming.
    """

    name = "gemini"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:{action}"

    def __init__(self):
        self._api_key = LLM_PROVIDERS.get("GEMINI")
        if not self._api_key:
            raise ValueError("AISTUDIO_KEY manquante dans la config")

    def _build_body(self, request: LLMRequest) -> dict:
        contents, system_prompt = _build_gemini_messages(request)

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature":    request.temperature,
                "maxOutputTokens": request.max_tokens,
            },
        }
        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        # Gemini utilise responseMimeType au lieu de response_format
        if request.response_format == "json":
            body["generationConfig"]["responseMimeType"] = "application/json"

        if request.tools:
            body["tools"] = _openai_tools_to_gemini(request.tools)
            tc = _openai_tool_choice_to_gemini(request.tool_choice)
            if tc:
                body["toolConfig"] = tc

        return body

    def _url(self, model: str, action: str) -> str:
        return self.BASE_URL.format(model=model, action=action)

    # ------------------------------------------------------------------ #
    #  Parsing d'un candidat Gemini                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_from_candidate(candidate: dict) -> tuple[str | None, list[LLMToolCall] | None]:
        """Extrait (texte, tool_calls) depuis un candidat Gemini."""
        parts = candidate.get("content", {}).get("parts", [])
        text_parts = []
        tool_calls = []

        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
            if "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(LLMToolCall(
                    id=fc.get("name", ""),   # Gemini n'a pas d'id séparé, on utilise le nom
                    name=fc["name"],
                    arguments=fc.get("args", {}),
                ))

        text = "".join(text_parts) or None
        return text, tool_calls or None

    # ------------------------------------------------------------------ #
    #  complete()                                                          #
    # ------------------------------------------------------------------ #

    async def complete(self, request: LLMRequest) -> LLMResponse:
        t0 = time.monotonic()
        body = self._build_body(request)
        url = self._url(request.model, "generateContent")

        try:
            async with httpx.AsyncClient(timeout=request.timeout) as client:
                resp = await client.post(
                    url, params={"key": self._api_key}, json=body
                )
                resp.raise_for_status()
                data = resp.json()

            candidate = data["candidates"][0]
            content, tool_calls = self._extract_from_candidate(candidate)
            usage = data.get("usageMetadata", {})

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                provider=self.name,
                model=request.model,
                prompt_tokens=usage.get("promptTokenCount", 0),
                completion_tokens=usage.get("candidatesTokenCount", 0),
                latency_ms=int((time.monotonic() - t0) * 1000),
                success=True,
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

    # ------------------------------------------------------------------ #
    #  stream()                                                            #
    # ------------------------------------------------------------------ #

    async def stream(self, request: LLMRequest) -> AsyncGenerator[LLMStreamChunk, None]:
        """
        Streaming Gemini via :streamGenerateContent.
        Gemini retourne un tableau JSON de chunks (pas SSE ligne par ligne).

        async for chunk in provider.stream(request):
            ...
        """
        t0 = time.monotonic()
        body = self._build_body(request)
        url = self._url(request.model, "streamGenerateContent")

        prompt_tokens = 0
        completion_tokens = 0

        try:
            async with httpx.AsyncClient(timeout=request.timeout) as client:
                async with client.stream(
                    "POST", url,
                    params={"key": self._api_key, "alt": "sse"},
                    json=body,
                ) as resp:
                    resp.raise_for_status()

                    async for raw_line in resp.aiter_lines():
                        if not raw_line.startswith("data:"):
                            continue
                        payload = raw_line[len("data:"):].strip()
                        if not payload:
                            continue

                        try:
                            chunk_data = json.loads(payload)
                        except json.JSONDecodeError:
                            continue

                        # Usage (présent sur le dernier chunk)
                        usage = chunk_data.get("usageMetadata", {})
                        if usage:
                            prompt_tokens = usage.get("promptTokenCount", prompt_tokens)
                            completion_tokens = usage.get("candidatesTokenCount", completion_tokens)

                        candidates = chunk_data.get("candidates", [])
                        if not candidates:
                            continue

                        candidate = candidates[0]
                        text, tool_calls = self._extract_from_candidate(candidate)

                        if text:
                            yield LLMStreamChunk(delta=text)

                        if tool_calls:
                            for tc in tool_calls:
                                yield LLMStreamChunk(tool_call=tc)

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
            logger.exception("Gemini stream erreur inattendue")
            yield LLMStreamChunk(
                done=True, success=False,
                error=str(e),
                provider=self.name, model=request.model,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )