from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Any


@dataclass
class LLMMessage:
    role: str     # "system" | "user" | "assistant" | "tool"
    content: str
    # Pour les messages role="tool" (résultat d'un appel d'outil)
    tool_call_id: Optional[str] = None
    # Pour les messages role="assistant" qui contiennent des tool_calls
    tool_calls: Optional[list[dict]] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LLMToolCall:
    """Un appel d'outil retourné par le modèle."""
    id:        str
    name:      str
    arguments: dict[str, Any]  # déjà désérialisé depuis JSON


@dataclass
class LLMRequest:
    messages:    list[LLMMessage]
    model:       str
    temperature: float = 0.1
    max_tokens:  int   = 1024
    timeout:     float = 30.0
    # Pour Ollama qwen3 — active le mode thinking
    think:       bool  = False
    response_format: Optional[str] = None  # valeur acceptée : "json"
    # Tool calling
    tools:       Optional[list[dict]] = None   # format OpenAI function-calling
    tool_choice: Optional[Any]        = None   # "auto" | "none" | "required" | {"type": "function", ...}
    # Streaming
    stream:      bool = False


@dataclass
class LLMResponse:
    content:           Optional[str]
    provider:          str
    model:             str
    prompt_tokens:     int   = 0
    completion_tokens: int   = 0
    latency_ms:        int   = 0
    success:           bool  = True
    error:             str   = ""
    # Tool calling
    tool_calls:        Optional[list[LLMToolCall]] = None

    @property
    def total_tokens(self):
        return self.completion_tokens + self.prompt_tokens

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class LLMStreamChunk:
    """
    Chunk émis pendant le streaming.

    Trois types possibles :
      - delta non vide, tool_call None  → fragment de texte
      - delta vide,    tool_call non None → outil appelé (chunk final de l'outil)
      - done=True                        → fin du stream (dernier chunk)
    """
    delta:      str                      = ""
    tool_call:  Optional[LLMToolCall]    = None
    done:       bool                     = False
    # Rempli uniquement sur le chunk done=True
    provider:          str = ""
    model:             str = ""
    prompt_tokens:     int = 0
    completion_tokens: int = 0
    latency_ms:        int = 0
    error:             str = ""
    success:           bool = True