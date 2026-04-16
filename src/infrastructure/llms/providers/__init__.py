from __future__ import annotations

import os
import traceback
from abc import ABC, abstractmethod

from src.domain.llm import LLMRequest, LLMResponse
from src.utils.tools import load_module


class LLMProvider(ABC):
    name: str = ""

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        ...

    def _error_response(self, error: str) -> LLMResponse:
        return LLMResponse(
            content="",
            provider=self.name,
            model="",
            success=False,
            error=error,
        )


def providers():
    data = {"main": [], "fast": [], "large": []}
    for f in os.listdir(os.path.dirname(__file__)):
        if f != "__init__.py" and f.endswith(".py"):
            f = os.path.join(os.path.dirname(__file__), f)
            try:
                with (load_module(f) as mod):
                    models = mod.MODELS
                    p = None
                    for x in dir(mod):
                        try:
                            c = getattr(mod, x)
                            if issubclass(c, mod.LLMProvider) and \
                                    c is not mod.LLMProvider:
                                p = x
                                _ = c()
                                break
                        except TypeError:

                            continue
                    if p:
                        for m, k in models.items():
                            data[m].append(
                                {
                                    "models": {
                                        "name": k[0],
                                        "thinking": k[1],
                                        "priority": k[2]
                                    },
                                    "provider": p,
                                    "file": f
                                }
                            )
            except ValueError:
                # pas de api_key pour ce llm
                pass
            except (ImportError, Exception):
                traceback.print_exc()
                pass
    data = {
        "main": sorted(data["main"], key=lambda x: x["models"]["priority"]),
        "fast": sorted(data["fast"], key=lambda x: x["models"]["priority"]),
        "large": sorted(data["large"], key=lambda x: x["models"]["priority"])
    }
    return data



if __name__ == '__main__':
    print(providers())