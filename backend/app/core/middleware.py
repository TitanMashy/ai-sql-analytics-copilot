from __future__ import annotations

import json
import math
import re
import time
from collections import defaultdict, deque
from threading import Lock
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def request_id_from_headers(headers: list[tuple[bytes, bytes]]) -> str:
    candidate = next(
        (value.decode("latin-1") for name, value in headers if name.lower() == b"x-request-id"),
        "",
    )
    return candidate if REQUEST_ID_PATTERN.fullmatch(candidate) else str(uuid4())


def error_response(
    status_code: int, code: str, message: str, request_id: str
) -> tuple[Message, list[Message]]:
    body = json.dumps(
        {"error": {"code": code, "message": message, "request_id": request_id}}
    ).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        (b"x-request-id", request_id.encode()),
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    ]
    return {"type": "http.response.start", "status": status_code, "headers": headers}, [
        {"type": "http.response.body", "body": body}
    ]


class RequestSizeLimitMiddleware:
    """Buffer only bounded request bodies, including requests without Content-Length."""

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers", [])
        state = scope.setdefault("state", {})
        request_id = state.get("request_id") or request_id_from_headers(headers)
        state["request_id"] = request_id
        content_length = next(
            (value for name, value in headers if name.lower() == b"content-length"), None
        )
        if content_length:
            try:
                if int(content_length) > self.max_body_bytes:
                    await self._reject(send, request_id)
                    return
            except ValueError:
                await self._reject(send, request_id)
                return

        messages: list[Message] = []
        body_size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            messages.append(message)
            body_size += len(message.get("body", b""))
            if body_size > self.max_body_bytes:
                await self._reject(send, request_id)
                return
            if not message.get("more_body", False):
                break

        message_index = 0

        async def replay_receive() -> Message:
            nonlocal message_index
            if message_index < len(messages):
                message = messages[message_index]
                message_index += 1
                return message
            return await receive()

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(send: Send, request_id: str) -> None:
        start, body = error_response(
            413,
            "REQUEST_TOO_LARGE",
            "Request body exceeds the configured size limit.",
            request_id,
        )
        await send(start)
        for message in body:
            await send(message)


class SlidingWindowRateLimiter:
    def __init__(self, requests: int, window_seconds: int) -> None:
        self.requests = requests
        self.window_seconds = window_seconds
        self._lock = Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(
        self, key: str, now: float | None = None, limit: int | None = None
    ) -> tuple[bool, int]:
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        allowed_requests = self.requests if limit is None else limit
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= allowed_requests:
                retry_after = max(1, math.ceil(self.window_seconds - (current - events[0])))
                return False, retry_after
            events.append(current)
            if len(self._events) > 4096:
                stale = [
                    item for item, times in self._events.items() if not times or times[-1] <= cutoff
                ]
                for item in stale:
                    self._events.pop(item, None)
            return True, 0
