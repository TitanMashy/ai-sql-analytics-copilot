"""Tests for the release tooling in the repository's top-level scripts/ directory."""

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    # Dataclasses with postponed annotations look their module up in sys.modules.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


release_notes = _load("release_notes")
smoke_test = _load("smoke_test")


# -- release notes --------------------------------------------------------------------------


def _notes(*commits: tuple[str, str, str]):
    notes = release_notes.Notes()
    for sha, subject, body in commits:
        notes.add(sha, subject, body)
    return notes


def test_commits_are_grouped_by_conventional_type() -> None:
    text = _notes(
        ("a1", "feat(api): add feedback endpoint", ""),
        ("b2", "fix: stop a crash on empty results", ""),
        ("c3", "docs(runbooks): add credential rotation", ""),
    ).render("v1.2.0")

    assert text.startswith("# v1.2.0")
    assert "## Features\n\n- **api:** add feedback endpoint (a1)" in text
    assert "## Bug fixes\n\n- stop a crash on empty results (b2)" in text
    assert "## Documentation\n\n- **runbooks:** add credential rotation (c3)" in text


def test_breaking_changes_come_first_from_a_bang_or_a_footer() -> None:
    text = _notes(
        ("a1", "feat!: drop the v0 endpoints", ""),
        ("b2", "fix(auth): tighten audience check", "Details.\n\nBREAKING CHANGE: tokens need aud"),
        ("c3", "chore: tidy", ""),
    ).render("v2.0.0")

    breaking = text.split("## Breaking changes")[1].split("##")[0]
    assert "drop the v0 endpoints (a1)" in breaking
    assert "tokens need aud (b2)" in breaking
    assert text.index("## Breaking changes") < text.index("## Features")


def test_unconventional_commits_are_listed_not_dropped() -> None:
    text = _notes(("a1", "Fixed the thing", ""), ("b2", "wip", "")).render("v1.0.1")

    assert "## Other changes" in text
    assert "- Fixed the thing (a1)" in text
    assert "- wip (b2)" in text


def test_an_empty_range_says_so() -> None:
    assert "No changes since the previous release." in release_notes.Notes().render("v1.0.0")


# -- smoke test -----------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    ready_body: dict = {"status": "ready"}
    ask_status = 200
    ask_body: dict = {"sql": "SELECT 1", "row_count": 1, "request_id": "r-1"}
    seen_authorization: list = []

    def log_message(self, *args) -> None:  # keep test output clean
        return

    def _send(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/v1/health":
            self._send(200, {"status": "ok", "database": "ok"})
        elif self.path == "/api/v1/health/ready":
            self._send(200, type(self).ready_body)
        else:
            self._send(404, {})

    def do_POST(self) -> None:  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        type(self).seen_authorization.append(self.headers.get("Authorization"))
        self._send(type(self).ask_status, type(self).ask_body)


@pytest.fixture
def server():
    _Handler.ready_body = {"status": "ready"}
    _Handler.ask_status = 200
    _Handler.ask_body = {"sql": "SELECT 1", "row_count": 1, "request_id": "r-1"}
    _Handler.seen_authorization = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _run(base_url: str, *extra: str) -> int:
    return smoke_test.main(["--base-url", base_url, "--wait", "2", "--timeout", "5", *extra])


def test_smoke_passes_and_sends_the_token(server, capsys) -> None:
    assert _run(server, "--token", "s3cret") == 0

    output = capsys.readouterr().out
    assert "ok   readiness: ready" in output
    assert "request r-1" in output
    assert _Handler.seen_authorization == ["Bearer s3cret"]
    assert "s3cret" not in output  # the token is never printed


def test_a_degraded_readiness_passes_unless_strict(server) -> None:
    _Handler.ready_body = {"status": "degraded", "degraded": ["llm_provider"]}

    assert _run(server) == 0
    with pytest.raises(SystemExit) as error:
        _run(server, "--strict")
    assert "degraded" in str(error.value)


def test_a_failed_ask_fails_the_smoke_test_with_the_request_id(server, capsys) -> None:
    _Handler.ask_status = 401
    _Handler.ask_body = {"error": {"code": "UNAUTHENTICATED", "request_id": "r-9"}}

    assert _run(server) == 1

    output = capsys.readouterr().out
    assert "HTTP 401" in output and "UNAUTHENTICATED" in output and "r-9" in output


def test_an_answer_without_sql_is_rejected(server) -> None:
    _Handler.ask_body = {"sql": "", "row_count": 1, "request_id": "r-1"}

    assert _run(server) == 1


def test_an_unreachable_environment_fails_fast(capsys) -> None:
    assert smoke_test.main(["--base-url", "http://127.0.0.1:1", "--wait", "1"]) == 1
    assert "FAIL liveness" in capsys.readouterr().out
