from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from utils.config import get_settings

_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "{message}"
)


def setup_logger(name: str = "smb-intel"):
    """Configure loguru sinks (stdout + rotating file) and return the logger."""
    level = get_settings().LOG_LEVEL

    logger.remove()
    logger.add(sys.stdout, format=_LOG_FORMAT, level=level, colorize=True)

    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    logger.add(
        logs_dir / f"{name}_{{time}}.log",
        format=_LOG_FORMAT,
        level=level,
        rotation="10 MB",
        retention="7 days",
        colorize=False,
        encoding="utf-8",
    )

    return logger
