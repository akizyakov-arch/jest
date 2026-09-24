"""Bounded diagnostic logs; no frames or landmarks are recorded."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(debug: bool, directory: Path | None = None) -> None:
    logger = logging.getLogger("gesture_control")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True)
        disk = RotatingFileHandler(directory / "gesture-control.log", maxBytes=1_000_000,
                                   backupCount=3, encoding="utf-8")
        disk.setFormatter(formatter)
        logger.addHandler(disk)
