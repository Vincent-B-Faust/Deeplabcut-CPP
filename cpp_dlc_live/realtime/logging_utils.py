from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from cpp_dlc_live.utils.io_utils import ensure_prefixed_filename


def setup_logging(
    session_dir: Path,
    logger_name: str = "cpp_dlc_live",
    file_prefix: Optional[str] = None,
) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)

    for h in list(logger.handlers):
        logger.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)

    log_filename = "run.log"
    if file_prefix:
        log_filename = ensure_prefixed_filename(log_filename, file_prefix)
    file_handler = logging.FileHandler(session_dir / log_filename, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)

    logger.addHandler(console)
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger
