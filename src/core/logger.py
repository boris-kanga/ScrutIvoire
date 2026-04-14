import logging
import logging.config
import os.path
import sys

from pathlib import Path
from src.core.config import APP_NAME

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    origin_name = name
    if name in sys.modules:
        m = Path(sys.modules[name].__file__)
        parts = m.parts
        if APP_NAME in parts:
            index = parts.index(APP_NAME)
            parts = list(parts[index:-1])
            try:
                parts.remove("src")
            except ValueError:
                pass
            if m.name != "__init__.py":
                parts.append(m.name.split(".")[0])
            name = ".".join(parts)
        else:
            pass
    log = logging.getLogger(name)
    _log_ = log._log

    def _log(
        level,
        msg,
        args,
        **kwargs,
    ):
        try:
            msg = str(msg) % args
        except (TypeError,Exception):
            msg = " ".join([str(msg), *[str(a) for a in args]])
        print(msg, file=sys.stderr)
        return _log_(level, msg, (), **kwargs)
    setattr(log, "_log", _log)
    return log


def setup_logging(
    app_name: str        = APP_NAME,
    log_level: str       = "INFO",
    log_to_file: bool    = True,
    log_to_console: bool = True,
):
    handlers = {}

    if log_to_console:
        handlers["console"] = {
            "class":     "logging.StreamHandler",
            "level":     log_level,
            "formatter": "detailed",
            "stream":    "ext://sys.stdout",
        }

    if log_to_file:
        handlers["file"] = {
            "class":       "logging.handlers.RotatingFileHandler",
            "level":       "DEBUG",   # ← capture tout, du DEBUG à CRITICAL
            "formatter":   "detailed",
            "filename":    LOG_DIR / f"{app_name}.log",
            "maxBytes":    10 * 1024 * 1024,
            "backupCount": 5,
            "encoding":    "utf-8",
        }

    logging.config.dictConfig({
        "version":                  1,
        "disable_existing_loggers": False,
        "formatters": {
            "detailed": {
                "format":  "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": handlers,
        "loggers": {
            app_name: {
                "level":     log_level,
                "handlers":  list(handlers.keys()),
                "propagate": False,
            },
        },
        "root": {
            "level":    "WARNING",
            "handlers": list(handlers.keys()),
        },
    })
