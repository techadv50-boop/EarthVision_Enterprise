from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.constants import APP_ID


def setup_logging(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    target = log_file.resolve()
    logger = logging.getLogger(APP_ID)
    logger.setLevel(logging.INFO)
    has_file = False
    for handler in list(logger.handlers):
        if isinstance(handler, RotatingFileHandler):
            if Path(handler.baseFilename) != target:
                logger.removeHandler(handler)
                handler.close()
            else:
                has_file = True
    if not has_file:
        handler = RotatingFileHandler(
            target,
            maxBytes=1_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    if not any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
        for h in logger.handlers
    ):
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(stream)
    return logger
