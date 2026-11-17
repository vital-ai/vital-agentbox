"""
Configurable JWT authentication middleware.

When AGENTBOX_JWT_ENABLED=true, all endpoints except GET /health and
/internal/* require a valid Bearer token.

Supports three key sources:
  1. JWKS URI (Keycloak / any OIDC provider) — auto-fetches and caches
     public keys. Set AGENTBOX_JWT_JWKS_URI.
  2. Static public key (RS256/ES256) — set AGENTBOX_JWT_PUBLIC_KEY.
  3. Shared secret (HS256) — set AGENTBOX_JWT_SECRET.

Keycloak integration:
  AGENTBOX_JWT_ENABLED=true
  AGENTBOX_JWT_JWKS_URI=https://keycloak.example.com/realms/myrealm/protocol/openid-connect/certs
  AGENTBOX_JWT_ISSUER=https://keycloak.example.com/realms/myrealm
  AGENTBOX_JWT_AUDIENCE=agentbox  (optional — Keycloak client_id)

  Keycloak realm_access.roles are automatically mapped to scopes.
"""

import os
import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DataAccessMode(str, Enum):
    """S3 data access scoping mode, configured at the service level.

    - tenant: S3 paths prefixed with JWT sub/tenant claim (default, current behavior)
    - path: caller specifies data_path, JWT is authentication only
    - path_credentials: caller specifies data_path + S3 credentials
    """
    TENANT = "tenant"
    PATH = "path"
    PATH_CREDENTIALS = "path_credentials"

from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware

try:
    import jwt as pyjwt
    from jwt import PyJWKClient
except ImportError:
    pyjwt = None
    PyJWKClient = None

logger = logging.getLogger(__name__)


@dataclass
class JWTConfig:
    enabled: bool = False
    secret: Optional[str] = None
    public_key: Optional[str] = None
    jwks_uri: Optional[str] = None
    algorithm: str = "RS256"
    issuer: Optional[str] = None
    audience: Optional[str] = None
    # Keycloak-specific: client_id used for audience validation
    client_id: Optional[str] = None
    # Service-to-service HS256 secret (worker ↔ orchestrator)
    service_secret: Optional[str] = None
    # Claim mapping
    roles_claim: str = "realm_access.roles"
    scope_claim: str = "scope"
    tenant_claim: str = "sub"
    admin_role: str = "admin"
    data_access_mode: DataAccessMode = DataAccessMode.TENANT

    @classmethod
    def from_env(cls) -> "JWTConfig":
        mode_str = os.environ.get("AGENTBOX_DATA_ACCESS_MODE", "tenant").lower()
        try:
            data_access_mode = DataAccessMode(mode_str)
        except ValueError:
            data_access_mode = DataAccessMode.TENANT
            logger.warning("Invalid AGENTBOX_DATA_ACCESS_MODE=%r, defaulting to 'tenant'", mode_str)
        return cls(
            enabled=os.environ.get("AGENTBOX_JWT_ENABLED", "").lower() == "true",
            secret=os.environ.get("AGENTBOX_JWT_SECRET"),
            public_key=os.environ.get("AGENTBOX_JWT_PUBLIC_KEY"),
            jwks_uri=os.environ.get("AGENTBOX_JWT_JWKS_URI"),
            algorithm=os.environ.get("AGENTBOX_JWT_ALGORITHM", "RS256"),
            issuer=os.environ.get("AGENTBOX_JWT_ISSUER"),
            audience=os.environ.get("AGENTBOX_JWT_AUDIENCE"),
            client_id=os.environ.get("AGENTBOX_JWT_CLIENT_ID"),
            service_secret=os.environ.get("AGENTBOX_SERVICE_SECRET"),
            roles_claim=os.environ.get("AGENTBOX_JWT_ROLES_CLAIM", "realm_access.roles"),
            scope_claim=os.environ.get("AGENTBOX_JWT_SCOPE_CLAIM", "scope"),
            tenant_claim=os.environ.get("AGENTBOX_JWT_TENANT_CLAIM", "sub"),
            admin_role=os.environ.get("AGENTBOX_JWT_ADMIN_ROLE", "admin"),
            data_access_mode=data_access_mode,
        )


# Paths that never require auth
EXEMPT_PATHS = {"/health", "/internal/health", "/docs", "/openapi.json", "/redoc"}


@dataclass
class TokenClaims:
    """Decoded JWT claims available to route handlers."""
    sub: Optional[str] = None  # tenant identifier
    scope: Optional[str] = None  # space-separated scopes/roles
    roles: list = field(default_factory=list)  # parsed role list
    sandbox_limit: Optional[int] = None
    raw: dict = field(default_factory=dict)  # full decoded payload


# ---------------------------------------------------------------------------
# JWKS key cache (for Keycloak / OIDC)
# ---------------------------------------------------------------------------

class _JWKSKeyCache:
    """Caches JWKS keys with a configurable TTL to avoid hitting Keycloak on every request."""

    def __init__(self, jwks_uri: str, cache_ttl: int = 300):
        self._jwks_uri = jwks_uri
        self._cache_ttl = cache_ttl
        self._jwks_client: Optional["PyJWKClient"] = None
        self._last_refresh: float = 0

    def _get_client(self) -> "PyJWKClient":
        if PyJWKClient is None:
            raise HTTPException(status_code=500, detail="PyJWT[crypto] not installed")
        if self._jwks_client is None:
            self._jwks_client = PyJWKClient(self._jwks_uri, cache_keys=True, lifespan=self._cache_ttl)
        return self._jwks_client

    def get_signing_key(self, token: str):
        """Get the signing key for the given token from the JWKS endpoint."""
        client = self._get_client()
        try:
            return client.get_signing_key_from_jwt(token)
        except Exception as e:
            logger.warning("JWKS key fetch failed: %s", e)
            raise HTTPException(status_code=401, detail=f"Failed to fetch signing key: {e}")


# Module-level cache, lazily initialized
_jwks_cache: Optional[_JWKSKeyCache] = None


def _get_jwks_cache(config: JWTConfig) -> _JWKSKeyCache:
    global _jwks_cache
    if _jwks_cache is None and config.jwks_uri:
        _jwks_cache = _JWKSKeyCache(config.jwks_uri)
    return _jwks_cache


# ---------------------------------------------------------------------------
# Token decoding
# ---------------------------------------------------------------------------

def _extract_nested_claim(payload: dict, claim_path: str):
    """Extract a nested claim like 'realm_access.roles' from a JWT payload."""
    parts = claim_path.split(".")
    current = payload
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def decode_token(token: str, config: JWTConfig) -> TokenClaims:
    """Decode and validate a JWT token. Raises HTTPException on failure."""
    if pyjwt is None:
        raise HTTPException(status_code=500, detail="PyJWT not installed")

    # Determine the signing key
    if config.jwks_uri:
        # JWKS (Keycloak / OIDC) — fetch key by kid from token header
        cache = _get_jwks_cache(config)
        signing_key = cache.get_signing_key(token)
        key = signing_key.key
        algorithms = [config.algorithm]
    elif config.algorithm.startswith("RS") or config.algorithm.startswith("ES"):
        key = config.public_key
        algorithms = [config.algorithm]
    else:
        key = config.secret
        algorithms = [config.algorithm]

    if key is None:
        raise HTTPException(status_code=500, detail="JWT key not configured")

    # Build decode options
    kwargs = {"algorithms": algorithms}
    if config.issuer:
        kwargs["issuer"] = config.issuer
    if config.audience:
        kwargs["audience"] = config.audience
    elif config.client_id:
        kwargs["audience"] = config.client_id

    try:
        payload = pyjwt.decode(token, key, **kwargs)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    # Extract scopes/roles — merge Keycloak realm_access.roles + standard scope claim
    roles = []
    keycloak_roles = _extract_nested_claim(payload, config.roles_claim)
    if isinstance(keycloak_roles, list):
        roles.extend(keycloak_roles)

    # Also check resource_access.<client_id>.roles (Keycloak client roles)
    if config.client_id:
        client_roles = _extract_nested_claim(
            payload, f"resource_access.{config.client_id}.roles"
        )
        if isinstance(client_roles, list):
            roles.extend(client_roles)

    # Standard OIDC scope claim (space-separated string)
    scope_str = payload.get(config.scope_claim, "")
    if isinstance(scope_str, str) and scope_str:
        roles.extend(scope_str.split())

    # Deduplicate
    roles = list(dict.fromkeys(roles))
    scope = " ".join(roles)

    # Extract tenant identifier
    tenant = _extract_nested_claim(payload, config.tenant_claim)

    return TokenClaims(
        sub=tenant if isinstance(tenant, str) else payload.get("sub"),
        scope=scope,
        roles=roles,
        sandbox_limit=payload.get("sandbox_limit"),
        raw=payload,
    )


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class JWTMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that enforces JWT auth when enabled."""

    def __init__(self, app, config: JWTConfig):
        super().__init__(app)
        self.config = config

    async def dispatch(self, request: Request, call_next):
        from starlette.responses import JSONResponse

        # Skip if JWT not enabled
        if not self.config.enabled:
            request.state.claims = TokenClaims()
            return await call_next(request)

        # Skip exempt paths
        path = request.url.path
        if path in EXEMPT_PATHS:
            request.state.claims = TokenClaims()
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        logger.debug("JWT middleware: method=%s path=%s has_auth=%s",
                     request.method, path, auth_header.startswith("Bearer "))
        try:
            claims = authenticate_bearer(auth_header, self.config)
        except HTTPException as e:
            logger.debug("JWT auth failed: %s", e.detail)
            return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
        request.state.claims = claims
        logger.debug("JWT middleware: auth OK, sub=%s", claims.sub)

        return await call_next(request)


class WebSocketJWTMiddleware:
    """ASGI middleware enforcing JWT auth on WebSocket handshakes.

    ``JWTMiddleware`` is a ``BaseHTTPMiddleware``, which only sees HTTP
    requests, so without this every WebSocket route is unauthenticated.
    Rejects the handshake (close 1008) when the Authorization header is
    missing or invalid; otherwise exposes the claims as ``websocket.state.claims``.
    """

    def __init__(self, app, config: JWTConfig):
        self.app = app
        self.config = config

    async def __call__(self, scope, receive, send):
        if scope["type"] != "websocket":
            return await self.app(scope, receive, send)

        state = scope.setdefault("state", {})
        if not self.config.enabled or scope.get("path") in EXEMPT_PATHS:
            state["claims"] = TokenClaims()
            return await self.app(scope, receive, send)

        auth_header = ""
        for name, value in scope.get("headers") or []:
            if name == b"authorization":
                auth_header = value.decode("latin-1")
                break
        try:
            state["claims"] = authenticate_bearer(auth_header, self.config)
        except HTTPException as e:
            logger.info("WebSocket auth rejected for %s: %s", scope.get("path"), e.detail)
            await send({"type": "websocket.close", "code": 1008})
            return
        return await self.app(scope, receive, send)


def authenticate_bearer(auth_header: str, config: JWTConfig) -> TokenClaims:
    """Validate an ``Authorization: Bearer`` header value and return its claims.

    Tries the HS256 service token first (fast path), then user-token validation
    (JWKS / public key / secret). Raises HTTPException(401) when missing or invalid.
    """
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = auth_header[7:]
    if config.service_secret:
        service_claims = _try_service_token(token, config.service_secret)
        if service_claims:
            return service_claims
    return decode_token(token, config)


# ---------------------------------------------------------------------------
# Service token helpers
# ---------------------------------------------------------------------------

def _try_service_token(token: str, service_secret: str) -> Optional[TokenClaims]:
    """Attempt to decode a service JWT (HS256). Returns None if not valid."""
    if pyjwt is None:
        return None
    try:
        payload = pyjwt.decode(token, service_secret, algorithms=["HS256"])
        if payload.get("type") != "service":
            return None
        return TokenClaims(
            sub=payload.get("sub", "service"),
            scope="service",
            roles=["service"],
            raw=payload,
        )
    except pyjwt.ExpiredSignatureError:
        logger.debug("Service token expired")
        return None
    except Exception as e:
        logger.debug("Service token decode failed: %s", e)
        return None


def mint_service_token(service_secret: str, subject: str, ttl: int = 60) -> str:
    """Mint a short-lived HS256 service JWT for worker↔orchestrator communication.

    Args:
        service_secret: Shared secret (AGENTBOX_SERVICE_SECRET).
        subject: Identifier (e.g. worker ID).
        ttl: Token lifetime in seconds (default 60).

    Returns:
        Signed JWT string.
    """
    if pyjwt is None:
        raise RuntimeError("PyJWT not installed — cannot mint service tokens")
    payload = {
        "sub": subject,
        "type": "service",
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl,
    }
    return pyjwt.encode(payload, service_secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_admin_role(request: Request) -> str:
    """Get the configured admin role name from the app's JWT config."""
    config = getattr(request.app.state, "jwt_config", None)
    if config:
        return config.admin_role
    return "admin"


def require_scope(request: Request, scope: str) -> TokenClaims:
    """Helper: raise 403 if the request doesn't have the required scope."""
    claims = getattr(request.state, "claims", TokenClaims())
    if not claims.scope:
        return claims  # No auth enforced
    admin_role = get_admin_role(request)
    if admin_role in claims.roles or scope in claims.roles:
        return claims
    raise HTTPException(status_code=403, detail=f"Scope '{scope}' required")
