"""Optional, sanitized LangSmith tracing of the model pipeline.

Off by default. When ``LANGSMITH_TRACING=true`` and a key is configured, each analytics operation
is recorded as a small tree of runs (operation, context retrieval, prompt construction, model
invocation, response parsing, SQL validation, repair, execution) carrying **only allowlisted
metadata**: request id, provider, model, outcome category, error code, attempt and repair counts,
row and table counts, and the evaluation case id. Runs are created with empty inputs, so the
question, the prompt, the generated SQL, result rows, conversation history, tenant and customer
identifiers, tokens and keys are never part of a trace. Errors are recorded as a code, never as an
exception message (a database error can contain SQL and parameters).

LangChain's own automatic tracing would record the whole prompt, so it is suspended around the
model call (``suspend_langchain_tracing``) whatever the environment says.

Tracing is never on the request path of the application's correctness:

* Spans are handed to a bounded in-process queue with a non-blocking ``put``; a daemon worker
  exports them with short timeouts, no retries, and a circuit breaker. When LangSmith is slow or
  down, runs are dropped, not waited for. (LangSmith's own batching client was measured to delay
  process exit by 45 seconds against an unreachable endpoint, which is why it is not used.)
* Every tracing operation is wrapped so that no tracing error can propagate; exceptions raised by
  the traced code itself pass through untouched.
* Shutdown waits at most about a second for the queue to drain.
"""

from __future__ import annotations

import atexit
import contextlib
import contextvars
import logging
import queue
import re
import threading
import time
from collections.abc import Iterator, Mapping
from typing import Any

from app.core.config import Settings
from app.core.telemetry import get_request_telemetry

logger = logging.getLogger(__name__)

# The only metadata keys that can reach a trace. Everything else is dropped.
ALLOWED_METADATA = frozenset(
    {
        "request_id",
        "operation",
        "provider",
        "model",
        "outcome",
        "error_code",
        "attempt",
        "max_attempts",
        "repair_count",
        "repair_attempt",
        "row_count",
        "tables_count",
        "validation_status",
        "case_id",
        "duration_ms",
    }
)
# String values must be a single short token. Question text, SQL and prose contain spaces,
# quotes or parentheses, so they cannot pass by accident even under an allowed key.
_SAFE_STRING = re.compile(r"^[A-Za-z0-9_.:\-/]{1,96}$")

_QUEUE_SIZE = 2000
_BREAKER_FAILURES = 5
_BREAKER_PAUSE_SECONDS = 30.0
_DRAIN_SECONDS_AT_EXIT = 1.0


def sanitize_metadata(values: Mapping[str, Any] | None) -> dict[str, str | int | float | bool]:
    """Keep only allowlisted keys with short scalar values."""
    clean: dict[str, str | int | float | bool] = {}
    for key, value in (values or {}).items():
        if key not in ALLOWED_METADATA or value is None:
            continue
        if isinstance(value, bool | int | float):
            clean[key] = value
        elif isinstance(value, str) and _SAFE_STRING.fullmatch(value):
            clean[key] = value
    return clean


def _error_code(error: BaseException) -> str:
    """A short, content-free label for an exception: its ``code`` if it has a safe one."""
    code = getattr(error, "code", None)
    if isinstance(code, str) and _SAFE_STRING.fullmatch(code):
        return code
    return type(error).__name__[:96]


# -- exporter ------------------------------------------------------------------------------------


class _Exporter:
    """Sends sanitized runs to LangSmith from a daemon thread; never blocks the caller."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._queue: queue.Queue[tuple[str, Any, dict[str, Any]]] = queue.Queue(_QUEUE_SIZE)
        self._failures = 0
        self._paused_until = 0.0
        self._last_warning = 0.0
        self.dropped = 0
        self._thread = threading.Thread(target=self._work, name="llm-trace-export", daemon=True)
        self._thread.start()

    # The two methods RunTree calls on its client.
    def create_run(self, **payload: Any) -> None:
        self._submit("create", None, payload)

    def update_run(self, run_id: Any, **payload: Any) -> None:
        self._submit("update", run_id, payload)

    def _submit(self, operation: str, run_id: Any, payload: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait((operation, run_id, payload))
        except queue.Full:
            self.dropped += 1

    def flush(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        return self._queue.unfinished_tasks == 0

    def _work(self) -> None:
        while True:
            operation, run_id, payload = self._queue.get()
            try:
                if time.monotonic() < self._paused_until:
                    self.dropped += 1  # circuit open: do not even try
                elif operation == "create":
                    self._client.create_run(**payload)
                    self._failures = 0
                else:
                    self._client.update_run(run_id, **payload)
                    self._failures = 0
            except Exception as error:
                self._failures += 1
                if self._failures >= _BREAKER_FAILURES:
                    self._paused_until = time.monotonic() + _BREAKER_PAUSE_SECONDS
                    self._failures = 0
                self._warn(error)
            finally:
                self._queue.task_done()

    def _warn(self, error: Exception) -> None:
        now = time.monotonic()
        if now - self._last_warning > 60:
            self._last_warning = now
            # The error type only: provider text could echo request details.
            logger.warning(
                "LangSmith export failed; tracing is best-effort",
                extra={"error_type": type(error).__name__},
            )


class _Tracer:
    def __init__(self, exporter: _Exporter, project: str) -> None:
        self.exporter = exporter
        self.project = project


_tracer: _Tracer | None = None
_current: contextvars.ContextVar[Any | None] = contextvars.ContextVar("llm_trace_run", default=None)
_case_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "llm_trace_case", default=None
)


def _build_client(settings: Settings) -> Any:
    from langsmith import Client
    from urllib3.util import Retry

    key = settings.langsmith_api_key.get_secret_value() if settings.langsmith_api_key else None
    return Client(
        api_url=settings.langsmith_endpoint,
        api_key=key,
        # Synchronous calls from the worker thread, so a failure is seen and bounded here.
        auto_batch_tracing=False,
        timeout_ms=(1000, 2000),
        retry_config=Retry(total=0),
        omit_traced_runtime_info=True,
        # Defense in depth: our runs are already sanitized.
        hide_inputs=lambda _inputs: {},
        hide_outputs=lambda outputs: sanitize_metadata(outputs),
        hide_metadata=lambda metadata: sanitize_metadata(metadata),
    )


def configure_llm_tracing(settings: Settings, client: Any | None = None) -> bool:
    """Enable tracing when configured; otherwise make sure it is off. Never raises.

    ``client`` replaces the LangSmith client (tests). Returns True when tracing is active.
    """
    global _tracer
    _tracer = None
    if not settings.langsmith_tracing:
        return False
    has_key = bool(settings.langsmith_api_key and settings.langsmith_api_key.get_secret_value())
    if client is None and not has_key:
        logger.warning("LANGSMITH_TRACING is true but LANGSMITH_API_KEY is not set; tracing is off")
        return False
    try:
        exporter = _Exporter(client if client is not None else _build_client(settings))
        _tracer = _Tracer(exporter, settings.langsmith_project)
    except Exception as error:
        logger.warning(
            "LangSmith tracing could not start", extra={"error_type": type(error).__name__}
        )
        return False
    return True


def tracing_enabled() -> bool:
    return _tracer is not None


def flush_llm_tracing(timeout: float = 5.0) -> bool:
    """Wait for queued runs to be exported (evaluation runs and tests); True when drained."""
    tracer = _tracer
    return tracer.exporter.flush(timeout) if tracer else True


def dropped_runs() -> int:
    tracer = _tracer
    return tracer.exporter.dropped if tracer else 0


@atexit.register
def _drain_at_exit() -> None:
    with contextlib.suppress(Exception):
        flush_llm_tracing(_DRAIN_SECONDS_AT_EXIT)


# -- spans ---------------------------------------------------------------------------------------


class TraceHandle:
    """Attach more metadata to the span being recorded. Safe to use when tracing is off."""

    __slots__ = ("_error", "_extra", "_run")

    def __init__(self, run: Any | None) -> None:
        self._run = run
        self._extra: dict[str, Any] = {}
        self._error: str | None = None

    def set(self, **values: Any) -> None:
        if self._run is not None:
            self._extra.update(values)

    def fail(self, code: str) -> None:
        if self._run is not None and _SAFE_STRING.fullmatch(code or ""):
            self._error = code


_NULL_HANDLE = TraceHandle(None)


def _start(name: str, metadata: Mapping[str, Any]) -> Any | None:
    tracer = _tracer
    if tracer is None:
        return None
    try:
        from langsmith.run_trees import RunTree

        values = dict(metadata)
        telemetry = get_request_telemetry()
        if telemetry is not None:
            values.setdefault("request_id", telemetry.request_id)
        parent = _current.get()
        if parent is not None:
            run = parent.create_child(
                name=name,
                run_type="chain",
                inputs={},
                extra={"metadata": sanitize_metadata(values)},
            )
        else:
            case_id = _case_id.get()
            if case_id:
                values.setdefault("case_id", case_id)
            run = RunTree(
                name=name,
                run_type="chain",
                inputs={},
                extra={"metadata": sanitize_metadata(values)},
                project_name=tracer.project,
                ls_client=tracer.exporter,
            )
        run.post()
        return run
    except Exception as error:
        _note_tracing_error(error)
        return None


def _finish(run: Any, handle: TraceHandle, started: float, failure: str | None) -> None:
    try:
        extra = dict(handle._extra)
        error = failure or handle._error
        extra.setdefault("outcome", "error" if error else "ok")
        if error:
            extra.setdefault("error_code", error)
        extra["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        clean = sanitize_metadata(extra)
        run.add_metadata(clean)
        run.end(outputs=clean, error=error)
        run.patch()
    except Exception as error:
        _note_tracing_error(error)


def _note_tracing_error(error: Exception) -> None:
    logger.debug("LLM tracing error", extra={"error_type": type(error).__name__})


@contextlib.contextmanager
def stage(name: str, **metadata: Any) -> Iterator[TraceHandle]:
    """Record one pipeline stage. A no-op when tracing is off; never alters the traced code.

    Exceptions from the body propagate unchanged and are recorded as a code only.
    """
    run = _start(name, metadata)
    if run is None:
        yield _NULL_HANDLE
        return
    handle = TraceHandle(run)
    token = _current.set(run)
    started = time.perf_counter()
    failure: str | None = None
    try:
        yield handle
    except BaseException as error:
        failure = _error_code(error)
        raise
    finally:
        _current.reset(token)
        _finish(run, handle, started, failure)


@contextlib.contextmanager
def trace_case(case_id: str) -> Iterator[None]:
    """Tag the next root operation with an evaluation case id."""
    token = _case_id.set(case_id)
    try:
        yield
    finally:
        _case_id.reset(token)


@contextlib.contextmanager
def suspend_langchain_tracing() -> Iterator[None]:
    """Switch off LangChain's automatic tracing, which would record the full prompt and reply."""
    try:
        from langsmith.run_helpers import tracing_context
    except Exception:
        yield
        return
    with tracing_context(enabled=False):
        yield
