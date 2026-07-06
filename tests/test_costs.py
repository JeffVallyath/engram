from engram import costs


def test_estimate_sonnet():
    # 10k input, 1k output on sonnet ($3/$15 per M) = 0.03 + 0.015 = $0.045
    assert abs(costs.estimate("claude-sonnet-5", 10_000, 1_000) - 0.045) < 1e-9


def test_estimate_matches_by_prefix():
    # dated/suffixed ids still resolve
    assert costs.estimate("claude-haiku-4-5-20251001", 1_000_000, 0) == 1.0


def test_cache_reads_are_cheaper():
    # in_tok is uncached input only; a fully-cached prefix reads at 0.1x
    full = costs.estimate("claude-sonnet-5", 10_000, 0)
    cached = costs.estimate("claude-sonnet-5", 0, 0, cache_read=10_000)
    assert cached < full
    assert abs(cached - full * 0.1) < 1e-9


def test_cache_writes_carry_the_surcharge():
    full = costs.estimate("claude-sonnet-5", 10_000, 0)
    written = costs.estimate("claude-sonnet-5", 0, 0, cache_write=10_000)
    assert abs(written - full * 1.25) < 1e-9


def test_unknown_model_returns_none():
    assert costs.estimate("some-random-model", 1000, 1000) is None


def test_record_logs_without_crashing(caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="engram.costs"):
        costs.record("claude-sonnet-5", 1, 8000, 600, cards=20)
    assert "draft cost" in caplog.text
    assert "model=claude-sonnet-5" in caplog.text
