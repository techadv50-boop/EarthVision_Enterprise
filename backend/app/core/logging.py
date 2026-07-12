"""Enterprise logging configuration using Loguru."""

import sys
from pathlib import Path

from loguru import logger

from app.core.config import PROJECT_ROOT, get_settings


def setup_logging() -> None:
    settings = get_settings()
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()

    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(sys.stderr, format=log_format, level="DEBUG" if settings.debug else "INFO")

    logger.add(
        log_dir / "earthvision_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="30 days",
        compression="zip",
        format=log_format,
        level="INFO",
        enqueue=True,
    )

    logger.add(
        log_dir / "earthvision_errors.log",
        rotation="10 MB",
        retention="90 days",
        format=log_format,
        level="ERROR",
        enqueue=True,
    )


def get_logger():
    return logger
