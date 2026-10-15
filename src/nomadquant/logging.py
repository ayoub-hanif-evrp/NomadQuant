"""JSON logs with defense-in-depth secret redaction."""

import json
import logging
import re
from datetime import UTC, datetime

from nomadquant.config import Settings

_ASSIGNMENT = re.compile(
    r"(?i)(api[_-]?key|api[_-]?secret|secret|authorization|bearer)"
    r"(\s*[:=]\s*|\s+)([^\s,;\"'}]+)"
)


def redact_text(text: str, secrets: list[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return _ASSIGNMENT.sub(r"\1\2[REDACTED]", redacted)


class RedactingJsonFormatter(logging.Formatter):
    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage(), self._secrets),
        }
        return redact_text(json.dumps(payload, ensure_ascii=True), self._secrets)


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingJsonFormatter(settings.secret_values))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
