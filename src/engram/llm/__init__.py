from __future__ import annotations

from typing import Optional

from ..config import Config
from .base import LLMClient, LLMDraftError, MissingAPIKeyError

__all__ = ["make_client", "LLMClient", "LLMDraftError", "MissingAPIKeyError"]


def make_client(cfg: Config) -> Optional[LLMClient]:
    # manual returns None — the app routes straight to the template path,
    # the LLM is an optional accelerator, not the core dependency
    provider = cfg.llm.provider
    if provider == "manual":
        return None
    if provider == "fake":
        from .fake import FakeClient
        return FakeClient()
    if provider == "anthropic":
        from .anthropic_client import AnthropicClient
        return AnthropicClient(cfg)
    if provider == "openai":
        from .openai_client import OpenAIClient
        return OpenAIClient(cfg)
    raise ValueError(f"unknown provider: {provider}")
