"""Authentication and the request principal.

Two modes are supported, selected by ``AUTH_MODE``:

* ``jwt``: signed bearer tokens validated for signature, expiry, issuer and audience.
* ``disabled``: no credentials required; every request is a local development admin.

The principal carries the tenant (``customer_id``) that the analytics executor uses to scope
database access, so authentication is part of the data-protection boundary, not just a gate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

ANALYTICS_ADMIN_ROLE = "analytics_admin"


@dataclass(frozen=True)
class Principal:
    user_id: str
    customer_id: int | None = None
    roles: tuple[str, ...] = ()
    authenticated: bool = True

    @property
    def is_global(self) -> bool:
        """Global principals may read every tenant. Everyone else is scoped to one customer."""
        return ANALYTICS_ADMIN_ROLE in self.roles


DEVELOPMENT_PRINCIPAL = Principal(
    user_id="development-anonymous",
    customer_id=None,
    roles=(ANALYTICS_ADMIN_ROLE,),
    authenticated=False,
)


def _unauthenticated(message: str = "Authentication is required.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthenticated()
    return token.strip()


def _jwt_principal(token: str, settings: Settings) -> Principal:
    try:
        import jwt  # PyJWT; imported lazily so non-JWT modes do not need it at runtime.
    except ImportError as error:  # pragma: no cover - dependency is declared in pyproject
        logger.error("PyJWT is not installed but AUTH_MODE=jwt is configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is temporarily unavailable.",
        ) from error

    if settings.jwt_algorithm == "HS256":
        key = settings.jwt_secret.get_secret_value() if settings.jwt_secret else ""
    else:
        key = settings.jwt_public_key.get_secret_value() if settings.jwt_public_key else ""
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )
    except jwt.PyJWTError as error:
        # Never echo the library's message: it can describe which claim failed.
        logger.info("JWT rejected", extra={"error_type": type(error).__name__})
        raise _unauthenticated("Invalid or expired credentials.") from error

    roles_claim = claims.get("roles", [])
    roles = tuple(str(role) for role in roles_claim) if isinstance(roles_claim, list) else ()
    raw_customer_id = claims.get("customer_id")
    customer_id: int | None
    try:
        customer_id = int(raw_customer_id) if raw_customer_id is not None else None
    except (TypeError, ValueError) as error:
        raise _unauthenticated("Invalid credentials.") from error

    principal = Principal(user_id=str(claims["sub"]), customer_id=customer_id, roles=roles)
    if not principal.is_global and principal.customer_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The credentials are not associated with a customer.",
        )
    return principal


def authenticate(request: Request, settings: Settings | None = None) -> Principal:
    settings = settings or get_settings()
    if settings.auth_mode == "disabled":
        if settings.is_production:  # defense in depth; configuration validation also rejects it
            raise _unauthenticated()
        return DEVELOPMENT_PRINCIPAL
    return _jwt_principal(_bearer_token(request), settings)


def get_principal(request: Request) -> Principal:
    """FastAPI dependency: authenticate once per request and cache the principal."""
    cached = getattr(request.state, "principal", None)
    if cached is not None:
        return cached
    principal = authenticate(request)
    request.state.principal = principal
    return principal
