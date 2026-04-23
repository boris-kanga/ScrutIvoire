from __future__ import annotations

import json
import re
import time
from typing import AsyncGenerator, TYPE_CHECKING

import httpx

from src.domain.llm import LLMRequest, LLMResponse, LLMStreamChunk, LLMToolCall

if TYPE_CHECKING:
    pass


def _serialize_messages(request: LLMRequest) -> list[dict]:
    """Convertit les LLMMessage en dicts OpenAI."""
    out = []
    for m in request.messages:
        msg: dict = {"role": m.role, "content": m.content or ""}
        if m.tool_call_id:
            msg["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            # Message assistant qui a déclenché des outils
            msg["tool_calls"] = m.tool_calls
            msg["content"] = m.content or ""
        out.append(msg)
    return out


def _extract_tool_calls_from_content(content: str) -> list[LLMToolCall] | None:
    """
    Fallback : certains modèles (llama petits) mettent les tool_calls
    directement dans le content au lieu du champ dédié.

    Format détecté :
        {"type": "function", "name": "fn_name", "arguments": {...}}
        séparés par ";" ou "\n" ou seuls.
    """
    if not content or '"type": "function"' not in content:
        return None

    result = []
    # Extraire tous les blocs JSON du texte
    for match in re.finditer(r'\{[^{}]*"type"\s*:\s*"function"[^{}]*\}', content):
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "function":
            continue
        name = obj.get("name") or obj.get("function", {}).get("name")
        args = obj.get("arguments") or obj.get("function", {}).get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if name:
            result.append(LLMToolCall(
                id=f"call_{len(result)}",
                name=name,
                arguments=args if isinstance(args, dict) else {},
            ))

    return result if result else None


def _parse_tool_calls(raw_tool_calls: list[dict]) -> list[LLMToolCall]:
    result = []
    for tc in raw_tool_calls:
        try:
            args = json.loads(tc["function"]["arguments"])
        except (json.JSONDecodeError, KeyError):
            args = {}
        result.append(LLMToolCall(
            id=tc["id"],
            name=tc["function"]["name"],
            arguments=args,
        ))
    return result


class OpenAICompatibleMixin:
    """
    Mixin à hériter EN PLUS de LLMProvider.
    La classe héritante doit définir : BASE_URL, name, _api_key.

    Flags surchargeables par provider :
      supports_response_format : bool — le provider accepte response_format (défaut True)
      supports_stream_usage    : bool — le provider retourne l'usage dans le chunk final SSE
    """

    BASE_URL: str
    name: str
    _api_key: str

    # Groq et OpenAI : oui. Cerebras : partiel (on l'active, si ça plante on désactive).
    supports_response_format: bool = True
    # Groq et Cerebras supportent stream_options. OpenAI aussi.
    supports_stream_usage: bool = True

    # Peut être surchargé par le provider pour injecter des headers extra
    def _extra_headers(self) -> dict:
        return {}

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            **self._extra_headers(),
        }

    def _build_body(self, request: LLMRequest) -> dict:
        body: dict = {
            "model":       request.model,
            "messages":    _serialize_messages(request),
            "temperature": request.temperature,
            "max_tokens":  request.max_tokens,
        }
        if request.tools:
            body["tools"] = request.tools
            if request.tool_choice is not None:
                body["tool_choice"] = request.tool_choice
        if request.response_format == "json":
            body["response_format"] = {"type": "json_object"}
        if request.stream:
            body["stream"] = True
            if self.supports_stream_usage:
                body["stream_options"] = {"include_usage": True}
        return body

    # ------------------------------------------------------------------ #
    #  Réponse non-streamée                                                #
    # ------------------------------------------------------------------ #

    def _parse_response(
        self,
        data: dict,
        request: LLMRequest,
        t0: float,
    ) -> LLMResponse:
        message = data["choices"][0]["message"]
        usage = data.get("usage", {})
        content = message.get("content")

        # Cas 1 : tool_calls dans le champ dédié (comportement normal)
        raw_tool_calls = message.get("tool_calls")
        tool_calls = _parse_tool_calls(raw_tool_calls) if raw_tool_calls else None

        # Cas 2 : fallback — modèle a mis les tool_calls dans le content
        if tool_calls is None and content:
            tool_calls = _extract_tool_calls_from_content(content)
            if tool_calls:
                # Le content ne contient que les tool_calls, on le vide
                content = None

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            provider=self.name,
            model=request.model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=int((time.monotonic() - t0) * 1000),
            success=True,
        )

    # ------------------------------------------------------------------ #
    #  Streaming                                                           #
    # ------------------------------------------------------------------ #

    async def _stream(
        self,
        request: LLMRequest,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        """
        AsyncGenerator qui yield des LLMStreamChunk.

        Usage :
            async for chunk in provider._stream(request):
                if chunk.done:
                    ...
                elif chunk.tool_call:
                    ...
                else:
                    print(chunk.delta, end="", flush=True)
        """
        t0 = time.monotonic()
        body = self._build_body(request)

        # Accumulation des tool_calls fragmentés sur plusieurs chunks
        # structure : {index: {"id": ..., "name": ..., "arguments": ""}}
        tool_call_acc: dict[int, dict] = {}

        prompt_tokens = 0
        completion_tokens = 0

        try:
            async with httpx.AsyncClient(timeout=request.timeout) as client:
                async with client.stream(
                    "POST",
                    self.BASE_URL,
                    headers=self._headers(),
                    json=body,
                ) as resp:
                    resp.raise_for_status()

                    async for raw_line in resp.aiter_lines():
                        if not raw_line.startswith("data:"):
                            continue
                        payload = raw_line[len("data:"):].strip()
                        if payload == "[DONE]":
                            break

                        try:
                            chunk_data = json.loads(payload)
                        except json.JSONDecodeError:
                            continue

                        # Usage (chunk final avec stream_options)
                        if chunk_data.get("usage"):
                            u = chunk_data["usage"]
                            prompt_tokens = u.get("prompt_tokens", prompt_tokens)
                            completion_tokens = u.get("completion_tokens", completion_tokens)

                        choices = chunk_data.get("choices", [])
                        if not choices:
                            continue

                        delta = choices[0].get("delta", {})
                        finish_reason = choices[0].get("finish_reason")

                        # --- Fragment de texte ---
                        text_delta = delta.get("content")
                        if text_delta:
                            yield LLMStreamChunk(delta=text_delta)

                        # --- Fragments de tool_calls ---
                        raw_tcs = delta.get("tool_calls")
                        if raw_tcs:
                            for tc_fragment in raw_tcs:
                                idx = tc_fragment.get("index", 0)
                                if idx not in tool_call_acc:
                                    tool_call_acc[idx] = {"id": "", "name": "", "arguments": ""}
                                acc = tool_call_acc[idx]
                                if tc_fragment.get("id"):
                                    acc["id"] = tc_fragment["id"]
                                fn = tc_fragment.get("function", {})
                                if fn.get("name"):
                                    acc["name"] = fn["name"]
                                if fn.get("arguments"):
                                    acc["arguments"] += fn["arguments"]

                        # --- Fin d'un appel d'outil ---
                        if finish_reason == "tool_calls":
                            for acc in tool_call_acc.values():
                                try:
                                    args = json.loads(acc["arguments"])
                                except json.JSONDecodeError:
                                    args = {}
                                yield LLMStreamChunk(
                                    tool_call=LLMToolCall(
                                        id=acc["id"],
                                        name=acc["name"],
                                        arguments=args,
                                    )
                                )
                            tool_call_acc.clear()

            # Chunk terminal
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
            yield LLMStreamChunk(
                done=True, success=False,
                error=str(e),
                provider=self.name, model=request.model,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )