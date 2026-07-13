"""Enterprise logging configuration with Loguru."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from app.core.config import get_settings


def setup_logging() -> None:
    """Configure structured application logging."""
    settings = get_settings()
    log_dir = settings.logs_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        sys.stdout,
        level="DEBUG" if settings.debug else "INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        enqueue=True,
        backtrace=settings.debug,
        diagnose=settings.debug,
    )
    logger.add(
        Path(log_dir) / "earthvision_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="30 days",
        compression="gz",
        level="INFO",
        enqueue=True,
    )
    logger.info("Logging initialized for {}", settings.app_name)
