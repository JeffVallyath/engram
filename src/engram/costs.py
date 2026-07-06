"""Per-draft token + cost logging, so you can see exactly what each capture
cost instead of guessing from the provider dashboard.

Prices are $ per million tokens (input, output), standard rates — an UPPER
bound, since intro discounts may make the real bill lower. Update if they
change; an unknown model just logs tokens with no dollar estimate."""

from __future__ import annotations

import logging

log = logging.getLogger("engram.costs")

PRICES = {
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.5, 10.0),
}

_session_total = 0.0


def _rate(model: str):
    for key, rate in PRICES.items():
        if model.startswith(key):
            return rate
    return None


def estimate(model: str, in_tok: int, out_tok: int, cache_read: int = 0, cache_write: int = 0):
    # in_tok is UNCACHED input only — the api reports uncached, cache-write
    # and cache-read tokens as separate counts. writes bill at 1.25x the
    # input rate, reads at 0.1x.
    rate = _rate(model)
    if rate is None:
        return None
    return ((in_tok / 1e6 * rate[0]) + (cache_write / 1e6 * rate[0] * 1.25)
            + (cache_read / 1e6 * rate[0] * 0.1) + (out_tok / 1e6 * rate[1]))


def record(model, attempts, in_tok, out_tok, cache_read=0, cache_write=0,
           has_image=False, cards=None):
    global _session_total
    cost = estimate(model, in_tok, out_tok, cache_read, cache_write)
    if cost is None:
        cost_s = "no price for this model"
    else:
        _session_total += cost
        cost_s = f"~${cost:.4f} (session ~${_session_total:.4f})"
    log.info(
        "draft cost: model=%s attempts=%d in=%d out=%d cache_read=%d cache_write=%d "
        "image=%s cards<=%s est=%s",
        model, attempts, in_tok, out_tok, cache_read, cache_write,
        "yes" if has_image else "no", cards, cost_s,
    )
    return cost
