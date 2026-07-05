from __future__ import annotations

import logging
import os
from pathlib import Path

LOG_PATH = Path.home() / ".engram" / "engram.log"


def content_logging_enabled() -> bool:
    # captured text comes from browsers, pdfs and private docs — content is
    # never logged unless the user opts in with ENGRAM_DEBUG=1
    return os.environ.get("ENGRAM_DEBUG") == "1"


def setup_logging():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if content_logging_enabled() else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
    )
