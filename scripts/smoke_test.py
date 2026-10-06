#!/usr/bin/env python3
"""Post-deploy smoke test: is the environment up, ready, and able to answer one question?

    python scripts/smoke_test.py --base-url https://staging.example.com --token "$SMOKE_TOKEN"

Checks, in order, and stops at the first failure (exit code 1):

1. ``GET /api/v1/health`` answers 200 (the process is up and reaches its application database).
2. ``GET /api/v1/health/ready`` answers 200 within ``--wait`` seconds. A body of
   ``{"status": "degraded"}`` is reported but accepted unless ``--strict`` is given: degraded means
   an optional dependency is unavailable, not that the release is broken.
3. ``POST /api/v1/analytics/ask`` (authenticated when ``--token`` is given) answers 200 with SQL,
   a row count, and a request id.

It uses only the standard library so it runs anywhere a release pipeline does, and it never prints
the token. The release workflow runs it against staging before promoting to production.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_QUESTION = "How many active vehicles do we have?"


def request_json(
    method: str,
    url: str,
    token: str | None,
    payload: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> tuple[int, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, _parse(response.read())
    except urllib.error.HTTPError as error:
        return error.code, _parse(error.read())


def _parse(body: bytes) -> Any:
    try:
        return json.loads(body.decode() or "null")
    except (ValueError, UnicodeDecodeError):
        return None


def wait_until_ready(base_url: str, wait_seconds: float, strict: bool) -> str:
    deadline = time.monotonic() + wait_seconds
    last = "no response"
    while True:
        try:
            status, body = request_json("GET", f"{base_url}/api/v1/health/ready", None, timeout=10)
            if status == 200:
                state = (body or {}).get("status", "ready")
                if state == "degraded" and strict:
                    raise SystemExit(f"FAIL readiness is degraded: {body}")
                return state
            last = f"HTTP {status}"
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last = type(error).__name__
        if time.monotonic() >= deadline:
            raise SystemExit(f"FAIL not ready after {wait_seconds:.0f}s (last: {last})")
        time.sleep(3)


def run(arguments: argparse.Namespace) -> int:
    base_url = arguments.base_url.rstrip("/")

    try:
        status, _ = request_json("GET", f"{base_url}/api/v1/health", None, timeout=10)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        print(f"FAIL liveness: {type(error).__name__}")
        return 1
    if status != 200:
        print(f"FAIL liveness: HTTP {status}")
        return 1
    print("ok   application database reachable (/api/v1/health)")

    state = wait_until_ready(base_url, arguments.wait, arguments.strict)
    print(f"ok   readiness: {state}")

    started = time.monotonic()
    status, body = request_json(
        "POST",
        f"{base_url}/api/v1/analytics/ask",
        arguments.token,
        {"question": arguments.question},
        timeout=arguments.timeout,
    )
    elapsed = time.monotonic() - started
    if status != 200 or not isinstance(body, dict):
        error = (body or {}).get("error", {}) if isinstance(body, dict) else {}
        print(
            f"FAIL ask: HTTP {status} code={error.get('code')} request_id={error.get('request_id')}"
        )
        return 1
    problems = []
    if not str(body.get("sql", "")).lstrip().upper().startswith(("SELECT", "WITH")):
        problems.append("response has no SELECT statement")
    if not isinstance(body.get("row_count"), int):
        problems.append("response has no row_count")
    if not body.get("request_id"):
        problems.append("response has no request_id")
    if problems:
        print("FAIL ask: " + "; ".join(problems))
        return 1
    print(
        f"ok   ask answered in {elapsed:.1f}s "
        f"({body['row_count']} rows, request {body['request_id']})"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a deployed environment.")
    parser.add_argument("--base-url", required=True, help="frontend or ingress URL")
    parser.add_argument("--token", help="bearer token for an authenticated ask")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--wait", type=float, default=120.0, help="seconds to wait for readiness")
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds to wait for an answer")
    parser.add_argument("--strict", action="store_true", help="fail when readiness is degraded")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
