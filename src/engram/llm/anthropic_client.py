from __future__ import annotations

import os

from ..config import Config
from ..models import CardDraftList, DraftRequest
from ..router import build_system_prompt, build_user_prompt
from .base import LLMDraftError, MissingAPIKeyError, draft_with_retry, output_budget


class AnthropicClient:
    def __init__(self, cfg: Config):
        try:
            import anthropic
        except ImportError as e:
            raise LLMDraftError(
                'the "anthropic" package is not installed — run: pip install engram[anthropic]'
            ) from e

        key = os.environ.get(cfg.llm.api_key_env)
        if not key:
            raise MissingAPIKeyError(
                f"{cfg.llm.api_key_env} is not set. Set it to your Anthropic API key "
                f"(or change llm.api_key_env in ~/.engram/config.toml)."
            )
        self.sdk = anthropic.Anthropic(api_key=key)
        self.model = cfg.llm.model
        self.cfg = cfg

    def draft_cards(self, req: DraftRequest) -> CardDraftList:
        system = build_system_prompt(req.max_cards, self.cfg.cards.cloze_max_deletions)
        user = build_user_prompt(req)

        content = []
        if req.image_b64:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": req.image_b64},
            })
        content.append({"type": "text", "text": user})

        budget = output_budget(req.max_cards)

        # streaming so a big budget can't hit http timeouts; schema is
        # enforced by our own pydantic validation + one corrective retry
        def send(corrective):
            msgs = [{"role": "user", "content": content}]
            if corrective:
                msgs.append({"role": "user", "content": corrective})
            with self.sdk.messages.stream(
                model=self.model, max_tokens=budget, system=system, messages=msgs
            ) as stream:
                resp = stream.get_final_message()
            return next((b.text for b in resp.content if b.type == "text"), "")

        return draft_with_retry(send)
