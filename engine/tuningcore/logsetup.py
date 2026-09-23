"""Logging voor TuningCore: élke actie komt in één roterend logbestand.

Doel: na een crash of "vastgelopen"-gevoel altijd terug te lezen wát hij
deed, waar precies (t/m welk bestand) en waarom het misging (volledige
traceback). Regels:

- Logbestand staat altijd NAAST de database: `<databank>.log`.
- Roteert bij 5 MB, houdt max 3 oudere versies bij — vult nooit je schijf.
- Élke batch wordt gelogd met duur + "t/m" bestand: de laatste logregel
  zegt altijd waar hij was. Daarmee is "waar loopt hij vast" meteen
  te beantwoorden.
- Fouten worden mét volledige Python-traceback gelogd én in de
  errors-tabel gezet.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback
from pathlib import Path

LOGGER_NAME = "tuningcore"
_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 5_000_000
_BACKUPS = 3

_logger: logging.Logger | None = None


def log_path_for(db_path: str | Path) -> Path:
    """Logbestand hoort altijd bij de database (zelfde naam + .log)."""
    return Path(str(db_path) + ".log")


def setup(db_path: str | Path) -> logging.Logger:
    """Activeer bestandslogging (idempotent; herhaalbaar via reset())."""
    global _logger
    if _logger is not None:
        return _logger
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    path = log_path_for(db_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8")
    except OSError:  # loggen mag N O O I T de reden van een crash zijn
        handler = None
    if handler is not None:
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
        logger.addHandler(handler)
    _logger = logger
    logger.info("=== TuningCore logging gestart (log: %s) ===", path)
    return logger


def reset() -> None:
    """Logconfiguratie loslaten (voor tests / herstart inzelfde proces)."""
    global _logger
    if _logger is not None:
        for handler in list(_logger.handlers):
            try:
                handler.close()
            except Exception:
                pass
            _logger.removeHandler(handler)
    _logger = None


def get() -> logging.Logger:
    """Logger zonder dat setup hoeft te hebben plaatsgevonden (nooit crashen)."""
    return logging.getLogger(LOGGER_NAME)


def log_exception(phase: str, exc: BaseException) -> str:
    """Volledige traceback in het log; geeft de tekst terug voor errors-tabel."""
    text = traceback.format_exc()
    get().error("[%s] EXCEPTION %s: %s\n%s", phase, type(exc).__name__, exc,
                text.rstrip())
    return text


def tail(db_path: str | Path, lines: int = 50) -> list[str]:
    """Laatste regels van het log (voor diagnose / meesturen bij vragen)."""
    path = log_path_for(db_path)
    if not path.exists():
        return []
    try:
        data = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return data[-max(lines, 1):]
