from __future__ import annotations

import contextlib
import json
import re
from typing import Any, AsyncGenerator, Union

from src.core.logger import get_logger
from src.domain.llm import LLMMessage, LLMRequest, LLMResponse, LLMStreamChunk
from src.infrastructure.llms.providers import (
    LLMProvider,
    providers
)
from src.utils.tools import load_module

logger = get_logger(__name__)


# Tâches Type Fast
_FAST_TYPE_TASKS = {"colum_detector", "chat"}

# Seuil tokens pour Type A long
_LONG_TEXT_TOKENS = 30_000


def _estimate_tokens(text: str) -> int:
    """Estimation rapide : ~4 caractères par token."""
    return len(text) // 4


@contextlib.contextmanager
def load_model(m):
    with load_module(m["file"]) as module:
        yield (
            getattr(module, m["provider"]),
            m["models"]["name"],
            m["models"]["thinking"]
        )


def _select_chain(
    task_type:       str,
    payload:         dict,
    permits:         tuple = (),
    response_format: str | None = None,
):
    """
    Sélectionne la chaîne de fallback selon le type de tâche.

    Si response_format est précisé, les providers qui déclarent
    supports_response_format=False sont exclus automatiquement
    avant même d'être tentés.
    """
    p = providers()

    if task_type in _FAST_TYPE_TASKS:
        key = "fast"
    else:
        key = "main"
        text = payload.get("text", "") or payload.get("body", "")
        estimated = _estimate_tokens(text)
        if estimated > _LONG_TEXT_TOKENS:
            key = "large"

    for c in p[key]:
        # Filtre sur les permits
        if permits and c["provider"] not in permits:
            continue

        # Filtre sur le support de response_format
        if response_format:
            with load_model(c) as (provider_cls, _, __):
                if not getattr(provider_cls, "supports_response_format", True):
                    logger.debug(
                        f"[{task_type}] skip {c['provider']} — "
                        f"supports_response_format=False"
                    )
                    continue

        yield c


def _parse_json_response(content: str) -> Union[dict, None]:
    """
    Extrait le JSON de la réponse LLM.
    Gère les cas où le LLM entoure le JSON de ```json ... ```.
    """
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", content)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{[\s\S]+}", content)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


class LLMRouter:
    def __init__(self, *args):
        self._permits = args

    # ------------------------------------------------------------------ #
    #  run() — réponse complète (JSON parsé)                               #
    # ------------------------------------------------------------------ #

    async def run(
        self,
        task_type:       str,
        messages:        list[LLMMessage],
        payload:         dict,
        timeout:         float = 30.0,
        temperature:     float = 0.1,
        max_tokens:      int   = 1024,
        response_format: str | None = None,
        tools:           list[dict] | None = None,
        tool_choice:     Any | None = None,
    ) -> dict[str, Any]:
        """
        Exécute la tâche LLM avec fallback automatique.

        Si response_format est précisé, seuls les providers qui supportent
        ce format sont tentés (filtre en amont dans _select_chain).

        Retourne un dict avec :
          - success: bool
          - result: dict | None  (JSON parsé, None si tool_calls)
          - tool_calls: list | None
          - provider, model, tokens, latency
        """
        for m in _select_chain(task_type, payload, self._permits, response_format):
            with load_model(m) as (provider_cls, model, think):
                request = LLMRequest(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    think=think,
                    response_format=response_format,
                    tools=tools,
                    tool_choice=tool_choice,
                )

                logger.info(f"[{task_type}] tentative {provider_cls.name}/{model}")
                response: LLMResponse = await provider_cls().complete(request)

                if not response.success:
                    logger.warning(
                        f"[{task_type}] {provider_cls.name} échoué "
                        f"({response.error}) → fallback"
                    )
                    continue

                # Cas tool_calls : on retourne sans parser de JSON
                if response.has_tool_calls:
                    logger.debug(
                        f"[{task_type}] tool_calls via {provider_cls.name}/{model} "
                        f"({response.latency_ms}ms)"
                    )
                    return {
                        "success":           True,
                        "result":            None,
                        "tool_calls":        [
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in response.tool_calls
                        ],
                        "provider":          response.provider,
                        "model":             response.model,
                        "prompt_tokens":     response.prompt_tokens,
                        "completion_tokens": response.completion_tokens,
                        "latency_ms":        response.latency_ms,
                    }

                # Cas texte : on parse le JSON
                parsed = _parse_json_response(response.content or "")
                if parsed is None:
                    logger.warning(
                        f"[{task_type}] {provider_cls.name} réponse non parsable "
                        f"→ fallback\n{(response.content or '')[:200]}"
                    )
                    continue

                logger.debug(
                    f"[{task_type}] succès via {provider_cls.name}/{model} "
                    f"({response.latency_ms}ms, {response.total_tokens}tok)"
                )
                return {
                    "success":           True,
                    "result":            parsed,
                    "tool_calls":        None,
                    "provider":          response.provider,
                    "model":             response.model,
                    "prompt_tokens":     response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "latency_ms":        response.latency_ms,
                }

        logger.error(f"[{task_type}] tous les providers ont échoué")
        return {
            "success":    False,
            "result":     None,
            "tool_calls": None,
            "error":      "all_providers_failed",
        }

    # ------------------------------------------------------------------ #
    #  stream() — AsyncGenerator[LLMStreamChunk]                          #
    # ------------------------------------------------------------------ #

    async def stream(
        self,
        task_type:       str,
        messages:        list[LLMMessage],
        payload:         dict,
        timeout:         float = 30.0,
        temperature:     float = 0.1,
        max_tokens:      int   = 1024,
        response_format: str | None = None,
        tools:           list[dict] | None = None,
        tool_choice:     Any | None = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        """
        Stream la réponse LLM avec fallback automatique.

        Si response_format est précisé, seuls les providers compatibles
        sont tentés (même filtre que run()).

        Usage :
            async for chunk in router.stream(task_type, messages, payload):
                if chunk.done:
                    break
                elif chunk.tool_call:
                    result = await dispatch(chunk.tool_call)
                elif chunk.delta:
                    print(chunk.delta, end="", flush=True)
        """
        for m in _select_chain(task_type, payload, self._permits, response_format):
            with load_model(m) as (provider_cls, model, think):
                provider = provider_cls()

                if not hasattr(provider, "stream"):
                    logger.warning(
                        f"[{task_type}] {provider_cls.name} ne supporte pas "
                        f"le streaming → fallback"
                    )
                    continue

                request = LLMRequest(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    think=think,
                    response_format=response_format,
                    tools=tools,
                    tool_choice=tool_choice,
                    stream=True,
                )

                logger.info(f"[{task_type}] stream via {provider_cls.name}/{model}")

                failed = False
                async for chunk in provider.stream(request):
                    if chunk.done and not chunk.success:
                        logger.warning(
                            f"[{task_type}] {provider_cls.name} stream échoué "
                            f"({chunk.error}) → fallback"
                        )
                        failed = True
                        break
                    yield chunk

                if not failed:
                    return  # stream terminé avec succès

        # Tous les providers ont échoué
        logger.error(f"[{task_type}] tous les providers stream ont échoué")
        yield LLMStreamChunk(
            done=True,
            success=False,
            error="all_providers_failed",
        )