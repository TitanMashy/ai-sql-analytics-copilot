import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.auth import ANALYTICS_ADMIN_ROLE, Principal
from app.core.config import Settings
from app.main import app

SECRET = "unit-test-secret-that-is-at-least-32-characters-long"
ISSUER = "https://issuer.example.test"
AUDIENCE = "analytics-api"
PROTECTED = "/api/v1/schema/tables"


def _use_settings(monkeypatch, settings: Settings) -> None:
    monkeypatch.setattr("app.core.auth.get_settings", lambda: settings)


def _jwt_settings(**overrides) -> Settings:
    values = {
        "auth_mode": "jwt",
        "jwt_algorithm": "HS256",
        "jwt_secret": SECRET,
        "jwt_issuer": ISSUER,
        "jwt_audience": AUDIENCE,
    }
    values.update(overrides)
    return Settings(**values)


def _token(**claims) -> str:
    jwt = pytest.importorskip("jwt")
    payload = {
        "sub": "user-1",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": int(time.time()) + 300,
        "customer_id": 7,
        "roles": ["analyst"],
    }
    payload.update(claims)
    return jwt.encode({k: v for k, v in payload.items() if v is not None}, SECRET, "HS256")


def _get(headers: dict[str, str] | None = None):
    with TestClient(app) as client:
        return client.get(PROTECTED, headers=headers)


def test_principal_global_scope_comes_from_the_admin_role_only() -> None:
    assert Principal("a", customer_id=1, roles=(ANALYTICS_ADMIN_ROLE,)).is_global
    assert not Principal("a", customer_id=1, roles=("analyst",)).is_global
    assert not Principal("a", customer_id=None).is_global


def test_disabled_mode_allows_requests_as_an_unauthenticated_admin(monkeypatch) -> None:
    _use_settings(monkeypatch, Settings(auth_mode="disabled"))

    assert _get().status_code == 200


def test_static_mode_requires_the_exact_token(monkeypatch) -> None:
    _use_settings(monkeypatch, Settings(auth_mode="static", auth_static_token="dev-token-value"))

    missing = _get()
    wrong = _get({"Authorization": "Bearer other"})
    wrong_scheme = _get({"Authorization": "Basic dev-token-value"})
    correct = _get({"Authorization": "Bearer dev-token-value"})

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "UNAUTHENTICATED"
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    assert wrong.status_code == 401
    assert wrong_scheme.status_code == 401
    assert correct.status_code == 200


def test_static_mode_is_rejected_in_production() -> None:
    # Defense in depth: configuration validation already refuses this combination at startup,
    # so the unvalidated constructor is used to reach the runtime check.
    from app.core.auth import authenticate

    settings = Settings.model_construct(
        environment="production",
        auth_mode="static",
        auth_static_token=SecretStr("dev-token-value"),
        auth_static_customer_id=None,
    )
    request = SimpleNamespace(headers={"authorization": "Bearer dev-token-value"})

    with pytest.raises(HTTPException) as error:
        authenticate(request, settings)  # type: ignore[arg-type]

    assert error.value.status_code == 401


def test_disabled_mode_is_rejected_in_production() -> None:
    from app.core.auth import authenticate

    settings = Settings.model_construct(environment="production", auth_mode="disabled")

    with pytest.raises(HTTPException) as error:
        authenticate(SimpleNamespace(headers={}), settings)  # type: ignore[arg-type]

    assert error.value.status_code == 401


def test_static_token_can_be_scoped_to_one_customer() -> None:
    from app.core.auth import _static_principal

    settings = Settings(
        auth_mode="static", auth_static_token="dev-token-value", auth_static_customer_id=9
    )

    principal = _static_principal("dev-token-value", settings)

    assert principal.customer_id == 9
    assert not principal.is_global


def test_valid_jwt_is_accepted(monkeypatch) -> None:
    _use_settings(monkeypatch, _jwt_settings())

    assert _get({"Authorization": f"Bearer {_token()}"}).status_code == 200


@pytest.mark.parametrize(
    "claims",
    [
        {"exp": int(time.time()) - 10},
        {"aud": "someone-else"},
        {"iss": "https://attacker.example.test"},
        {"sub": None},
        {"exp": None},
    ],
)
def test_invalid_jwts_are_rejected_without_detail(monkeypatch, claims) -> None:
    _use_settings(monkeypatch, _jwt_settings())

    response = _get({"Authorization": f"Bearer {_token(**claims)}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    # The message never says which check failed (expiry, audience, issuer, missing claim).
    assert response.json()["error"]["message"] == "Invalid or expired credentials."


def test_jwt_signed_with_another_key_is_rejected(monkeypatch) -> None:
    jwt = pytest.importorskip("jwt")
    _use_settings(monkeypatch, _jwt_settings())
    forged = jwt.encode(
        {
            "sub": "x",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": int(time.time()) + 60,
            "customer_id": 1,
        },
        "a-completely-different-secret-of-sufficient-length",
        "HS256",
    )

    assert _get({"Authorization": f"Bearer {forged}"}).status_code == 401


def test_unsigned_jwt_is_rejected(monkeypatch) -> None:
    jwt = pytest.importorskip("jwt")
    _use_settings(monkeypatch, _jwt_settings())
    unsigned = jwt.encode(
        {"sub": "x", "iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 60},
        None,
        algorithm="none",
    )

    assert _get({"Authorization": f"Bearer {unsigned}"}).status_code == 401


def test_non_admin_token_without_a_customer_is_forbidden(monkeypatch) -> None:
    _use_settings(monkeypatch, _jwt_settings())

    response = _get({"Authorization": f"Bearer {_token(customer_id=None)}"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_admin_token_does_not_need_a_customer(monkeypatch) -> None:
    _use_settings(monkeypatch, _jwt_settings())

    token = _token(customer_id=None, roles=[ANALYTICS_ADMIN_ROLE])

    assert _get({"Authorization": f"Bearer {token}"}).status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        ("get", "/api/v1/schema"),
        ("get", "/api/v1/schema/tables"),
        ("post", "/api/v1/analytics/conversations"),
        ("post", "/api/v1/analytics/ask"),
        ("post", "/api/v1/analytics/generate"),
        ("post", "/api/v1/analytics/query"),
        ("post", "/api/v1/analytics/validate"),
    ],
)
def test_every_protected_route_requires_credentials(monkeypatch, path) -> None:
    _use_settings(monkeypatch, Settings(auth_mode="static", auth_static_token="dev-token-value"))
    method, url = path

    with TestClient(app) as client:
        if method == "get":
            response = client.get(url)
        else:
            response = client.post(url, json={"question": "q", "sql": "SELECT 1"})

    assert response.status_code == 401


def test_health_endpoints_stay_open_without_credentials(monkeypatch) -> None:
    _use_settings(monkeypatch, Settings(auth_mode="static", auth_static_token="dev-token-value"))

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
