from __future__ import annotations

import os

from ..config import Config
from ..models import CardDraftList, DraftRequest
from ..router import build_system_prompt, build_user_prompt
from .base import LLMDraftError, MissingAPIKeyError, draft_with_retry

DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIClient:
    def __init__(self, cfg: Config):
        try:
            import openai
        except ImportError as e:
            raise LLMDraftError(
                'the "openai" package is not installed — run: pip install engram[openai]'
            ) from e

        key = os.environ.get(cfg.llm.api_key_env)
        if not key:
            raise MissingAPIKeyError(
                f"{cfg.llm.api_key_env} is not set. Set it to your OpenAI API key "
                f"(or change llm.api_key_env in ~/.engram/config.toml)."
            )
        self.sdk = openai.OpenAI(api_key=key)
        # config default is anthropic-flavored, swap it out unless overridden
        self.model = cfg.llm.model if not cfg.llm.model.startswith("claude") else DEFAULT_MODEL
        self.cfg = cfg

    def draft_cards(self, req: DraftRequest) -> CardDraftList:
        system = build_system_prompt(req.max_cards, self.cfg.cards.cloze_max_deletions)
        user = build_user_prompt(req)

        content = []
        if req.image_b64:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{req.image_b64}"},
            })
        content.append({"type": "text", "text": user})

        def send(corrective):
            msgs = [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ]
            if corrective:
                msgs.append({"role": "user", "content": corrective})
            resp = self.sdk.chat.completions.create(
                model=self.model,
                messages=msgs,
                response_format={"type": "json_object"},
                max_tokens=2048,
            )
            return resp.choices[0].message.content or ""

        return draft_with_retry(send)
