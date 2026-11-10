"""Persistent, interview-correlated backend diagnostics."""

import logging
import os
import re
import threading
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path


_interview_id = ContextVar("interview_id", default="-")
_interview_stage = ContextVar("interview_stage", default="-")
_configured = False
_thread_contexts: dict[int, tuple[str, str]] = {}
_thread_context_lock = threading.Lock()


class _RedactingFormatter(logging.Formatter):
    _patterns = (
        re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
        re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization)[\"']?\s*[:=]\s*[\"']?)[^,\s\"']+"),
        re.compile(r"\b(?:sk|xi)-[A-Za-z0-9_-]{16,}\b"),
    )

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        for pattern in self._patterns:
            rendered = pattern.sub(r"\1[REDACTED]" if pattern.groups else "[REDACTED]", rendered)
        for name, value in os.environ.items():
            if any(term in name.lower() for term in ("api_key", "token", "secret")) and len(value) >= 8:
                rendered = rendered.replace(value, "[REDACTED]")
        return rendered


class _InterviewContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        with _thread_context_lock:
            thread_context = _thread_contexts.get(record.thread)
        if not hasattr(record, "interview_id"):
            record.interview_id = (
                thread_context[0] if thread_context else _interview_id.get()
            )
        if not hasattr(record, "stage"):
            record.stage = (
                thread_context[1] if thread_context else _interview_stage.get()
            )
        return True


def set_interview_context(interview_id: int | str, stage: str):
    """Set IDs/stage for app and propagated SDK records in this execution context."""
    id_token = _interview_id.set(str(interview_id))
    stage_token = _interview_stage.set(stage)
    return id_token, stage_token


def set_interview_stage(stage: str) -> None:
    _interview_stage.set(stage)
    with _thread_context_lock:
        thread_id = threading.get_ident()
        if thread_id in _thread_contexts:
            interview_id, _ = _thread_contexts[thread_id]
            _thread_contexts[thread_id] = (interview_id, stage)


def bind_thread_context(thread_id: int, interview_id: int | str, stage: str) -> None:
    with _thread_context_lock:
        _thread_contexts[thread_id] = (str(interview_id), stage)


def unbind_thread_context(thread_id: int) -> None:
    with _thread_context_lock:
        _thread_contexts.pop(thread_id, None)


def set_thread_stage(thread_id: int, stage: str) -> None:
    with _thread_context_lock:
        context = _thread_contexts.get(thread_id)
        if context:
            _thread_contexts[thread_id] = (context[0], stage)


def reset_interview_context(tokens) -> None:
    id_token, stage_token = tokens
    _interview_stage.reset(stage_token)
    _interview_id.reset(id_token)


def configure_backend_logging() -> None:
    global _configured
    if _configured:
        return

    log_path = Path(__file__).resolve().parents[1] / "logs" / "interviews.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    # Keep unrelated libraries/application logs at WARNING by default. The
    # interview modules and ElevenLabs SDK opt in to INFO explicitly below.
    root.setLevel(logging.WARNING)
    handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(logging.INFO)
    handler.addFilter(_InterviewContextFilter())
    handler.setFormatter(_RedactingFormatter(
        "%(asctime)s %(levelname)s %(name)s "
        "interview_id=%(interview_id)s stage=%(stage)s %(message)s"
    ))
    if any(
        isinstance(existing, RotatingFileHandler)
        and Path(existing.baseFilename).resolve() == log_path.resolve()
        for existing in root.handlers
    ):
        handler.close()
    else:
        root.addHandler(handler)

    # The installed Conversational AI SDK emits WebSocket send/receive failures
    # through this logger. Keep its existing error diagnostics, without payloads.
    logging.getLogger("elevenlabs.conversational_ai.conversation").setLevel(logging.INFO)
    _configured = True
