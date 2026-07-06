from __future__ import annotations

import os

from .. import costs
from ..config import Config
from ..models import CardDraftList, DraftRequest
from ..router import build_system_prompt, build_user_prompt_parts
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
        source, task = build_user_prompt_parts(req)

        # source first with a cache marker: draft-more/revise resend an
        # identical system+source prefix within minutes and read it back at
        # 0.1x input price instead of paying for the whole document again.
        # one-shot captures pay a 1.25x write surcharge on that prefix —
        # small next to what one reuse saves. prefixes under ~1k tokens
        # simply don't cache; the marker is then a no-op.
        content = []
        if req.image_b64:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": req.image_b64},
            })
        content.append({"type": "text", "text": source,
                        "cache_control": {"type": "ephemeral"}})
        content.append({"type": "text", "text": task})

        budget = output_budget(req.max_cards)
        usages = []

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
            usages.append(resp.usage)
            return next((b.text for b in resp.content if b.type == "text"), "")

        try:
            return draft_with_retry(send)
        finally:
            if usages:
                # the api reports uncached, cache-write and cache-read input
                # separately; costs.estimate prices each at its own rate
                costs.record(
                    self.model, len(usages),
                    sum(getattr(u, "input_tokens", 0) for u in usages),
                    sum(getattr(u, "output_tokens", 0) for u in usages),
                    cache_read=sum(getattr(u, "cache_read_input_tokens", 0) or 0 for u in usages),
                    cache_write=sum(getattr(u, "cache_creation_input_tokens", 0) or 0 for u in usages),
                    has_image=bool(req.image_b64), cards=req.max_cards,
                )
