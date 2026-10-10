"""Optional LangSmith tracing: off by default, sanitized when on, and never able to hurt a request.

Nothing here reaches the real LangSmith. Runs go to a fake client, or (for the wire-level checks)
to a LangSmith-shaped server on 127.0.0.1.
"""

import json
import logging
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.analytics.service import AnalyticsQueryService, AnalyticsServiceError
from app.core import llm_tracing
from app.core.auth import Principal
from app.core.config import Settings, read_secret_files
from app.core.llm_tracing import (
    ALLOWED_METADATA,
    configure_llm_tracing,
    dropped_runs,
    flush_llm_tracing,
    sanitize_metadata,
    stage,
    trace_case,
    tracing_enabled,
)
from app.llm.langchain_provider import LangChainSQLProvider
from app.services.generation import SQLGenerationService

BACKEND = Path(__file__).resolve().parents[1]

# Distinctive values that must never appear in anything exported.
SECRET_QUESTION = "show salary of Alice Wonderland at Acme Corp"
SECRET_USER = "user-alice-secret"
SECRET_CUSTOMER = 987654
SECRET_API_KEY = "lsv2_pt_supersecretkeyvalue"
GOOD_SQL = (
    '{"sql":"SELECT COUNT(*) AS active_count FROM vehicles WHERE status = \'active\'",'
    '"explanation":"Counts the active vehicles.","tables_used":["vehicles"]}'
)
BAD_COLUMN = '{"sql":"SELECT missing_col FROM vehicles","explanation":"x","tables_used":[]}'


class FakeLangSmith:
    """Stands in for the LangSmith client and records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._lock = threading.Lock()

    def create_run(self, **kwargs) -> None:
        with self._lock:
            self.calls.append(("create", kwargs))

    def update_run(self, run_id, **kwargs) -> None:
        with self._lock:
            self.calls.append(("update", {"run_id": str(run_id), **kwargs}))

    def everything(self) -> str:
        return json.dumps(self.calls, default=str)

    def names(self) -> list[str]:
        return [call["name"] for kind, call in self.calls if kind == "create"]


class FakeChat:
    def __init__(self, *replies) -> None:
        self.replies = list(replies)

    def invoke(self, messages, *args, **kwargs):
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return SimpleNamespace(content=reply)


@pytest.fixture(autouse=True)
def tracing_off_afterwards():
    yield
    configure_llm_tracing(Settings())


@pytest.fixture
def traced() -> FakeLangSmith:
    client = FakeLangSmith()
    settings = Settings(langsmith_tracing=True, langsmith_api_key=SECRET_API_KEY)
    assert configure_llm_tracing(settings, client=client)
    return client


def _engine():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE vehicles (id INTEGER, status TEXT)"))
        connection.execute(text("INSERT INTO vehicles VALUES (1, 'active'), (2, 'inactive')"))
    return engine


def _service(*replies, max_repair_retries: int = 2) -> SQLGenerationService:
    provider = LangChainSQLProvider(
        name="gemini",
        label="Gemini",
        model="gemini-test",
        chat_model=FakeChat(*replies),
        max_retries=0,
        sleep=lambda seconds: None,
    )
    return SQLGenerationService(
        provider=provider,
        analytics_service=AnalyticsQueryService(_engine()),
        max_repair_retries=max_repair_retries,
    )


PRINCIPAL = Principal(SECRET_USER, customer_id=SECRET_CUSTOMER, roles=("analyst",))


# -- off by default ------------------------------------------------------------------------------


def test_tracing_is_off_by_default_and_creates_no_exporter() -> None:
    assert Settings().langsmith_tracing is False

    assert configure_llm_tracing(Settings()) is False
    with stage("anything", provider="x") as run:
        run.set(outcome="ok")

    assert tracing_enabled() is False
    assert not any(thread.name == "llm-trace-export" for thread in threading.enumerate())


def test_a_pipeline_request_needs_no_langsmith_when_tracing_is_off() -> None:
    result = _service(GOOD_SQL).ask(SECRET_QUESTION, principal=PRINCIPAL)

    assert result.result.rows == [{"active_count": 1}]


def test_enabling_tracing_without_a_key_leaves_it_off(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="app.core.llm_tracing"):
        enabled = configure_llm_tracing(Settings(langsmith_tracing=True))

    assert enabled is False and tracing_enabled() is False
    assert "LANGSMITH_API_KEY" in caplog.text


def test_the_langsmith_key_is_a_secret() -> None:
    settings = Settings(langsmith_tracing=True, langsmith_api_key=SECRET_API_KEY)

    assert SECRET_API_KEY not in repr(settings)
    assert SECRET_API_KEY not in settings.model_dump_json()


def test_the_langsmith_key_can_come_from_a_file(tmp_path) -> None:
    key_file = tmp_path / "langsmith_key"
    key_file.write_text(SECRET_API_KEY + "\n", encoding="utf-8")

    values = read_secret_files({"LANGSMITH_API_KEY_FILE": str(key_file)})

    assert values == {"langsmith_api_key": SECRET_API_KEY}


def test_the_langsmith_endpoint_must_be_http() -> None:
    with pytest.raises(ValueError, match="LANGSMITH_ENDPOINT"):
        Settings(langsmith_endpoint="ftp://example.test")


# -- sanitizing ----------------------------------------------------------------------------------


def test_only_allowlisted_scalar_metadata_survives() -> None:
    clean = sanitize_metadata(
        {
            "request_id": "3f2b6c1e-0d4a-4e0b-9a77-1d2c3e4f5a6b",
            "provider": "ollama",
            "model": "llama3.1:8b",
            "attempt": 2,
            "valid": True,
            "question": SECRET_QUESTION,
            "sql": "SELECT * FROM users",
            "customer_id": SECRET_CUSTOMER,
            "authorization": "Bearer abc",
            "api_key": SECRET_API_KEY,
            "rows": [{"a": 1}],
        }
    )

    assert clean == {
        "request_id": "3f2b6c1e-0d4a-4e0b-9a77-1d2c3e4f5a6b",
        "provider": "ollama",
        "model": "llama3.1:8b",
        "attempt": 2,
    }


@pytest.mark.parametrize(
    "value",
    [
        "SELECT id FROM vehicles",  # spaces: prose and SQL cannot pass under an allowed key
        "it's a question?",
        "x" * 97,
        "",
        ["a"],
        {"a": 1},
        None,
        "line\nbreak",
    ],
)
def test_content_like_values_are_dropped_even_under_an_allowed_key(value) -> None:
    assert sanitize_metadata({"outcome": value, "error_code": value, "model": value}) == {}


def test_every_allowed_key_is_a_known_name() -> None:
    assert "question" not in ALLOWED_METADATA
    assert (
        not {"sql", "rows", "customer_id", "tenant", "token", "prompt", "history"}
        & ALLOWED_METADATA
    )


# -- a traced request ----------------------------------------------------------------------------


def test_a_traced_ask_records_each_stage_with_only_safe_metadata(traced) -> None:
    service = _service(GOOD_SQL)

    with trace_case("fleet-01"):
        service.ask(SECRET_QUESTION, principal=PRINCIPAL, conversation_id=None)
    assert flush_llm_tracing()

    names = traced.names()
    for expected in (
        "analytics.ask",
        "context_retrieval",
        "prompt_construction",
        "model_invocation",
        "response_parsing",
        "sql_validation",
        "sql_execution",
    ):
        assert expected in names, names

    creates = [call for kind, call in traced.calls if kind == "create"]
    assert all(call["inputs"] == {} for call in creates)  # nothing goes in
    root = next(call for call in creates if call["name"] == "analytics.ask")
    assert root.get("parent_run_id") is None
    assert len({call["trace_id"] for call in creates}) == 1  # one tree
    assert all(call.get("parent_run_id") for call in creates if call is not root)

    metadata = root["extra"]["metadata"]
    assert metadata["provider"] == "gemini" and metadata["model"] == "gemini-test"
    assert metadata["operation"] == "ask" and metadata["case_id"] == "fleet-01"

    for _, call in traced.calls:
        for key in (call.get("extra") or {}).get("metadata", {}):
            assert key in ALLOWED_METADATA, key
        for key in call.get("outputs") or {}:
            assert key in ALLOWED_METADATA, key


def test_nothing_sensitive_is_exported(traced) -> None:
    service = _service(GOOD_SQL)

    service.ask(SECRET_QUESTION, principal=PRINCIPAL)
    assert flush_llm_tracing()
    exported = traced.everything()

    assert exported  # something was recorded
    for secret in (
        SECRET_QUESTION,
        "Alice",
        "Acme",
        SECRET_USER,
        str(SECRET_CUSTOMER),
        SECRET_API_KEY,
        "SELECT",  # the generated SQL
        "active_count",
        "inactive",  # a result row value
        "Counts the active vehicles",  # the model's explanation
        "Do not invent identifiers",  # the system prompt
    ):
        assert secret not in exported, secret


def test_a_repair_is_traced_with_its_attempt_and_error_code(traced) -> None:
    service = _service(BAD_COLUMN, GOOD_SQL)

    service.ask("count vehicles", principal=PRINCIPAL)
    assert flush_llm_tracing()

    creates = {call["name"]: call for kind, call in traced.calls if kind == "create"}
    assert "repair" in creates
    metadata = creates["repair"]["extra"]["metadata"]
    assert metadata["repair_attempt"] == 1
    assert metadata["error_code"]
    assert traced.names().count("sql_validation") == 2  # the repaired SQL is validated again
    root_update = [c for k, c in traced.calls if k == "update" and c["name"] == "analytics.ask"][0]
    assert root_update["outputs"]["outcome"] == "ok"  # the repaired answer succeeded


def test_provider_failure_is_traced_as_a_code_never_the_message(traced) -> None:
    leaky = ValueError("password=hunter2 SELECT * FROM users WHERE token='abc123'")
    service = _service(leaky)

    with pytest.raises(Exception) as raised:
        service.ask("count vehicles", principal=PRINCIPAL)
    assert flush_llm_tracing()
    exported = traced.everything()

    assert getattr(raised.value, "code", "") == "LLM_PROVIDER_ERROR"  # the request fails as before
    assert "hunter2" not in exported and "abc123" not in exported
    errors = [c["error"] for k, c in traced.calls if k == "update" and c.get("error")]
    assert errors and all(" " not in error for error in errors)
    assert "LLM_PROVIDER_ERROR" in errors


def test_a_database_error_is_traced_without_its_sql(traced) -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)  # no vehicles table
    provider = LangChainSQLProvider(
        name="gemini", label="Gemini", model="m", chat_model=FakeChat(GOOD_SQL), max_retries=0
    )
    service = SQLGenerationService(
        provider=provider, analytics_service=AnalyticsQueryService(engine), max_repair_retries=0
    )

    with pytest.raises(AnalyticsServiceError):
        service.ask(SECRET_QUESTION, principal=PRINCIPAL)
    assert flush_llm_tracing()
    exported = traced.everything()

    assert "active_count" not in exported and "no such table" not in exported.lower()
    assert SECRET_QUESTION not in exported


# -- tracing can never hurt a request ------------------------------------------------------------


def test_a_failing_langsmith_client_does_not_change_the_answer() -> None:
    class Broken:
        def create_run(self, **kwargs):
            raise ConnectionError("langsmith is down")

        def update_run(self, run_id, **kwargs):
            raise TimeoutError("langsmith is down")

    configure_llm_tracing(Settings(langsmith_tracing=True, langsmith_api_key="k"), client=Broken())

    result = _service(GOOD_SQL).ask(SECRET_QUESTION, principal=PRINCIPAL)

    assert result.result.rows == [{"active_count": 1}]
    assert flush_llm_tracing()  # the worker survived and drained the queue


def test_a_slow_langsmith_client_does_not_slow_the_request() -> None:
    release = threading.Event()

    class Slow:
        def create_run(self, **kwargs):
            release.wait(10)

        def update_run(self, run_id, **kwargs):
            release.wait(10)

    configure_llm_tracing(Settings(langsmith_tracing=True, langsmith_api_key="k"), client=Slow())
    service = _service(*([GOOD_SQL] * 5))
    started = time.perf_counter()

    try:
        for _ in range(5):
            service.ask(SECRET_QUESTION, principal=PRINCIPAL)
        elapsed = time.perf_counter() - started
    finally:
        release.set()

    assert elapsed < 2.0, elapsed  # exporting is blocked for 10 s each; the requests never wait


def test_exceptions_from_the_traced_code_pass_through_unchanged(traced) -> None:
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with stage("anything"):
            raise Boom("secret detail")
    flush_llm_tracing()

    assert "secret detail" not in traced.everything()


def test_the_circuit_breaker_stops_calling_a_dead_endpoint() -> None:
    calls = {"count": 0}

    class Dead:
        def create_run(self, **kwargs):
            calls["count"] += 1
            raise ConnectionError("down")

        def update_run(self, run_id, **kwargs):
            calls["count"] += 1
            raise ConnectionError("down")

    configure_llm_tracing(Settings(langsmith_tracing=True, langsmith_api_key="k"), client=Dead())
    for _ in range(40):
        with stage("op"):
            pass
    assert flush_llm_tracing(10)

    # 80 runs were queued; after five consecutive failures the exporter stops trying.
    assert calls["count"] <= 6
    assert dropped_runs() > 0


def test_langchain_automatic_tracing_is_suspended_around_the_model_call(monkeypatch) -> None:
    from langsmith import utils as ls_utils

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", SECRET_API_KEY)
    ls_utils.get_env_var.cache_clear()
    seen = []

    class Probe:
        def invoke(self, messages, *args, **kwargs):
            seen.append(ls_utils.tracing_is_enabled())
            return SimpleNamespace(content=GOOD_SQL)

    try:
        assert ls_utils.tracing_is_enabled() is True  # the ambient setting would auto-trace
        provider = LangChainSQLProvider(
            name="gemini", label="Gemini", model="m", chat_model=Probe(), max_retries=0
        )
        provider.generate_sql("q", SQLGenerationService(provider=provider).retriever.retrieve("q"))
    finally:
        ls_utils.get_env_var.cache_clear()

    assert seen == [False]


def test_the_case_id_tags_the_operation(traced) -> None:
    with trace_case("billing-03"):
        with stage("analytics.ask"):
            with stage("sql_validation"):
                pass
    assert flush_llm_tracing()

    creates = {call["name"]: call for kind, call in traced.calls if kind == "create"}
    assert creates["analytics.ask"]["extra"]["metadata"]["case_id"] == "billing-03"


def test_without_a_case_context_there_is_no_case_id(traced) -> None:
    with stage("analytics.ask"):
        pass
    assert flush_llm_tracing()

    root = next(c for k, c in traced.calls if k == "create")
    assert "case_id" not in root["extra"]["metadata"]


# -- the real client against a LangSmith-shaped server --------------------------------------------


class _FakeLangSmithServer:
    def __init__(self) -> None:
        self.bodies: list[tuple[str, str, bytes]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _respond(self, method: str) -> None:
                length = int(self.headers.get("Content-Length", 0) or 0)
                outer.bodies.append((method, self.path, self.rfile.read(length)))
                body = b"{}"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                self._respond("GET")

            def do_POST(self):  # noqa: N802
                self._respond("POST")

            def do_PATCH(self):  # noqa: N802
                self._respond("PATCH")

            def log_message(self, *args) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def test_the_real_langsmith_client_sends_only_sanitized_runs_over_the_wire() -> None:
    server = _FakeLangSmithServer()
    try:
        settings = Settings(
            langsmith_tracing=True,
            langsmith_api_key=SECRET_API_KEY,
            langsmith_endpoint=server.url,
            langsmith_project="proj-test",
        )
        assert configure_llm_tracing(settings)  # builds the real langsmith.Client

        with trace_case("fleet-02"):
            _service(GOOD_SQL).ask(SECRET_QUESTION, principal=PRINCIPAL)
        assert flush_llm_tracing(10)
    finally:
        server.close()

    runs = [
        (m, p, b) for m, p, b in server.bodies if p.rstrip("/").endswith("/runs") or "/runs/" in p
    ]
    assert runs, [(m, p) for m, p, _ in server.bodies]
    wire = b"\n".join(body for _, _, body in server.bodies).decode("utf-8", errors="replace")

    for secret in (
        SECRET_QUESTION,
        "Alice",
        "Acme",
        SECRET_USER,
        str(SECRET_CUSTOMER),
        "SELECT",
        "active_count",
        "inactive",
        "Do not invent identifiers",
    ):
        assert secret not in wire, secret
    assert "analytics.ask" in wire and "proj-test" in wire and "fleet-02" in wire


def test_the_wire_capture_can_see_a_leak_and_the_clients_own_hiding_removes_it() -> None:
    """Control for the wire test above: it must be capable of failing."""
    from langsmith import Client
    from langsmith.run_trees import RunTree

    def post_run_with_question(client) -> str:
        run = RunTree(
            name="control",
            run_type="chain",
            inputs={"question": SECRET_QUESTION},
            extra={"metadata": {"customer_id": SECRET_CUSTOMER, "outcome": "ok"}},
            project_name="p",
            ls_client=client,
        )
        run.post()
        run.end(outputs={"sql": "SELECT secret FROM t"})
        run.patch()
        return "\n".join(b.decode("utf-8", "replace") for _, _, b in server.bodies)

    server = _FakeLangSmithServer()
    try:
        plain = Client(api_url=server.url, api_key="k", auto_batch_tracing=False)
        leaked = post_run_with_question(plain)
        server.bodies.clear()
        settings = Settings(
            langsmith_tracing=True, langsmith_api_key="k", langsmith_endpoint=server.url
        )
        hidden = post_run_with_question(llm_tracing._build_client(settings))
    finally:
        server.close()

    assert SECRET_QUESTION in leaked  # an unprotected client does send it
    assert SECRET_QUESTION not in hidden  # our client's hide_inputs removes it
    assert "SELECT secret" not in hidden  # and hide_outputs keeps only allowlisted keys
    assert str(SECRET_CUSTOMER) not in hidden  # and hide_metadata drops the tenant id


def test_a_dead_langsmith_endpoint_does_not_delay_process_exit() -> None:
    script = (
        "import time\n"
        "from app.core.config import Settings\n"
        "from app.core.llm_tracing import configure_llm_tracing, stage\n"
        "configure_llm_tracing(Settings(langsmith_tracing=True, langsmith_api_key='k',"
        " langsmith_endpoint='http://127.0.0.1:9'))\n"
        "t = time.time()\n"
        "for _ in range(5):\n"
        "    with stage('analytics.ask', provider='mock'):\n"
        "        pass\n"
        "print(round(time.time() - t, 2))\n"
    )
    started = time.perf_counter()

    process = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=60,
    )
    total = time.perf_counter() - started

    assert process.returncode == 0, process.stderr[-500:]
    assert float(process.stdout.strip().splitlines()[-1]) < 1.0  # the request path
    # LangSmith's own client took 45 seconds to exit against the same dead endpoint.
    assert total < 15, total
