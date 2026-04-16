from __future__ import annotations

import contextlib
import json
import re
from typing import Any, Union

from src.core.logger import get_logger
from src.domain.llm import LLMMessage, LLMRequest, LLMResponse
from src.infrastructure.llms.providers import (
    LLMProvider,
    providers
)
from src.utils.tools import load_module

logger = get_logger(__name__)


# Tâches Type Fast
_FAST_TYPE_TASKS = {"colum_detector"}

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
    task_type: str,
    payload: dict,
    permits = ()
):
    """Sélectionne la chaîne de fallback selon le type de tâche."""

    p = providers()

    if task_type in _FAST_TYPE_TASKS:
        key = "fast"
    else:
        key = "main"
        text = payload.get("text", "") or payload.get("body", "")
        estimated = _estimate_tokens(text)
        if estimated > _LONG_TEXT_TOKENS:
            key = "large"
    candidate = p[key]
    for c in candidate:
        if permits and c["provider"] not in permits:
            continue
        yield c


def _parse_json_response(content: str) -> Union[dict, None]:
    """
    Extrait le JSON de la réponse LLM.
    Gère les cas où le LLM entoure le JSON de ```json ... ```.
    """
    # Essai direct
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Chercher un bloc ```json ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", content)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Chercher le premier { ... }
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

    async def run(
        self,
        task_type: str,
        messages:  list[LLMMessage],
        payload:   dict,
        timeout:   float = 30.0,
        temperature: float = 0.1,
        max_tokens:  int   = 1024,
        response_format: str=None
    ) -> dict[str, Any]:
        """
        Exécute la tâche LLM avec fallback automatique.

        Retourne un dict avec :
          - le résultat parsé (JSON)
          - les métadonnées (provider, model, tokens, latency)
          - success: bool
        """

        for m in _select_chain(task_type, payload, self._permits):
            with load_model(m) as (provider, model, think):
                request = LLMRequest(
                    messages    = messages,
                    model       = model,
                    temperature = temperature,
                    max_tokens  = max_tokens,
                    timeout     = timeout,
                    think       = think,
                    response_format=response_format
                )

                logger.info(
                    f"[{task_type}] tentative {provider.name}/{model}"
                )
                print(provider)
                response: LLMResponse = await provider().complete(request)

                if not response.success:
                    logger.warning(
                        f"[{task_type}] {provider.name} échoué "
                        f"({response.error}) → fallback"
                    )
                    continue

                # Parser le JSON
                parsed = _parse_json_response(response.content)
                if parsed is None:
                    logger.warning(
                        f"[{task_type}] {provider.name} réponse non parsable "
                        f"→ fallback\n{response.content[:200]}"
                    )
                    continue

                logger.debug(
                    f"[{task_type}] succès via {provider.name}/{model} "
                    f"({response.latency_ms}ms, "
                    f"{response.total_tokens}tok)"
                )

                return {
                    "success":           True,
                    "result":            parsed,
                    "provider":          response.provider,
                    "model":             response.model,
                    "prompt_tokens":     response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "latency_ms":        response.latency_ms,
                }

        # Tous les providers ont échoué
        logger.error(f"[{task_type}] tous les providers ont échoué")
        return {
            "success": False,
            "result":  None,
            "error":   "all_providers_failed",
        }

