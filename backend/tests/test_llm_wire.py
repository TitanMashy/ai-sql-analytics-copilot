"""The real LangChain clients against local fake servers (no external service, no model).

Unit tests with a fake chat model cannot show what the real clients do underneath, such as how many
HTTP requests a failing call makes. These tests point the genuine Gemini and Ollama chat classes at
a server on 127.0.0.1 that speaks just enough of each API.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.core.config import Settings
from app.llm.factory import build_llm_provider
from app.llm.provider import LLMProviderError
from app.services.schema_retriever import SchemaRetriever

SQL_REPLY = {
    "sql": "SELECT COUNT(*) AS n FROM vehicles",
    "explanation": "Counts vehicles.",
    "tables_used": ["vehicles"],
    "confidence": 0.8,
}


class _Server:
    def __init__(self, handler) -> None:
        self.hits: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                outer.hits.append(self.path)
                self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
                status, body = handler(self.path)
                payload = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def serve():
    servers: list[_Server] = []

    def start(handler) -> _Server:
        server = _Server(handler)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


def _context():
    return SchemaRetriever().retrieve("how many vehicles")


def _gemini(url: str, retries: int):
    settings = Settings(
        llm_provider="gemini",
        gemini_api_key="fake-key",
        llm_timeout_seconds=10,
        llm_max_retries=retries,
    )
    provider = build_llm_provider(settings)
    # Same class and arguments as the factory builds, aimed at the local server.
    provider.chat_model = type(provider.chat_model)(
        model=settings.effective_llm_model,
        google_api_key="fake-key",
        base_url=url,
        temperature=0,
        timeout=10,
        max_retries=0,
        response_mime_type="application/json",
    )
    return provider


@pytest.mark.parametrize("retries", [0, 1, 2])
def test_gemini_failures_make_exactly_one_plus_max_retries_requests(serve, retries) -> None:
    server = serve(
        lambda path: (
            503,
            {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}},
        )
    )

    with pytest.raises(LLMProviderError) as error:
        _gemini(server.url, retries).generate_sql("how many vehicles", _context())

    # No retries hidden inside LangChain or the Google client: the app's policy is the only one.
    assert len(server.hits) == 1 + retries
    assert error.value.code == "LLM_PROVIDER_UNAVAILABLE"


def test_gemini_rate_limit_is_not_retried(serve) -> None:
    server = serve(
        lambda path: (
            429,
            {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}},
        )
    )

    with pytest.raises(LLMProviderError) as error:
        _gemini(server.url, 2).generate_sql("how many vehicles", _context())

    assert len(server.hits) == 1
    assert error.value.code == "LLM_RATE_LIMITED"


def test_gemini_invalid_key_is_reported_as_invalid_credentials(serve) -> None:
    body = {
        "error": {
            "code": 400,
            "message": "API key not valid. Please pass a valid API key.",
            "status": "INVALID_ARGUMENT",
        }
    }
    server = serve(lambda path: (400, body))

    with pytest.raises(LLMProviderError) as error:
        _gemini(server.url, 1).generate_sql("how many vehicles", _context())

    assert error.value.code == "LLM_CREDENTIALS_INVALID"
    assert len(server.hits) == 1
    assert "not valid" not in error.value.message  # provider text is never echoed


def _ollama(url: str, retries: int = 0):
    return build_llm_provider(
        Settings(
            llm_provider="ollama",
            llm_model="test-model",
            ollama_base_url=url,
            llm_timeout_seconds=5,
            llm_max_retries=retries,
        )
    )


def _ollama_chat(content: str) -> bytes:
    """One NDJSON line in the shape of Ollama's /api/chat reply."""
    line = {
        "model": "test-model",
        "created_at": "2026-01-01T00:00:00Z",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop",
    }
    return (json.dumps(line) + "\n").encode()


def test_ollama_reply_is_parsed_through_the_shared_parser(serve) -> None:
    server = serve(lambda path: (200, _ollama_chat(json.dumps(SQL_REPLY))))

    result = _ollama(server.url).generate_sql("how many vehicles", _context())

    assert result.sql == SQL_REPLY["sql"]
    assert server.hits == ["/api/chat"]


def test_ollama_malformed_reply_is_a_classified_failure(serve) -> None:
    server = serve(lambda path: (200, _ollama_chat("sorry, I cannot help with that")))

    with pytest.raises(LLMProviderError) as error:
        _ollama(server.url).generate_sql("how many vehicles", _context())

    assert error.value.code == "INVALID_LLM_RESPONSE"


def test_ollama_model_that_was_not_pulled_is_reported_not_downloaded(serve) -> None:
    server = serve(
        lambda path: (404, {"error": "model 'test-model' not found, try pulling it first"})
    )

    with pytest.raises(LLMProviderError) as error:
        _ollama(server.url).generate_sql("how many vehicles", _context())

    assert error.value.code == "LLM_MODEL_UNAVAILABLE"
    # Only the chat request: nothing was pulled or pre-checked implicitly.
    assert server.hits == ["/api/chat"]


def test_ollama_that_is_not_running_fails_promptly_with_provider_unavailable() -> None:
    started = time.monotonic()

    with pytest.raises(LLMProviderError) as error:
        _ollama("http://127.0.0.1:9", retries=1).generate_sql("how many vehicles", _context())

    assert error.value.code == "LLM_PROVIDER_UNAVAILABLE"
    assert error.value.status_code == 503
    # Refused connections fail fast; a stopped Ollama must never turn into an indefinite hang.
    assert time.monotonic() - started < 15
