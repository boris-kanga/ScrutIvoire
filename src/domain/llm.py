from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMMessage:
    role: str     # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMRequest:
    messages:    list[LLMMessage]
    model:       str
    temperature: float = 0.1
    max_tokens:  int   = 1024
    timeout:     float = 30.0
    # Pour Ollama qwen3 — active le mode thinking
    think:       bool  = False
    response_format: Optional[str] = None


@dataclass
class LLMResponse:
    content:           str
    provider:          str
    model:             str
    prompt_tokens:     int   = 0
    completion_tokens: int   = 0
    latency_ms:        int   = 0
    success:           bool  = True
    error:             str   = ""

    @property
    def total_tokens(self):
        return self.completion_tokens + self.prompt_tokens
