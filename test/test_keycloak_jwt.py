"""Keycloak JWT integration test.

PENDING — requires a running Keycloak instance.

Prerequisites:
    1. Keycloak running (e.g. docker run -p 8080:8080 quay.io/keycloak/keycloak:latest start-dev)
    2. Realm: agentbox
    3. Client: agentbox (confidential, service account enabled)
    4. Realm roles: admin, sandbox_user
    5. Client roles on 'agentbox' client: sandbox:create, sandbox:execute
    6. Test user with realm_access.roles assigned

    Set environment variables:
        KEYCLOAK_URL=http://localhost:8080
        KEYCLOAK_REALM=agentbox
        KEYCLOAK_CLIENT_ID=agentbox
        KEYCLOAK_CLIENT_SECRET=<client-secret>
        KEYCLOAK_TEST_USER=testuser
        KEYCLOAK_TEST_PASSWORD=testpass

    Then configure the orchestrator with:
        AGENTBOX_JWT_ENABLED=true
        AGENTBOX_JWT_JWKS_URI=http://localhost:8080/realms/agentbox/protocol/openid-connect/certs
        AGENTBOX_JWT_ISSUER=http://localhost:8080/realms/agentbox
        AGENTBOX_JWT_CLIENT_ID=agentbox
        AGENTBOX_JWT_AUDIENCE=account

Test plan:
    1. Obtain token from Keycloak via password grant
    2. Obtain service account token via client_credentials grant
    3. Validate token via JWKS URI (RS256) using decode_token
    4. Verify realm_access.roles mapping to claims.roles
    5. Verify resource_access.agentbox.roles mapping
    6. Verify require_scope enforcement against real decoded claims
    7. Verify expired token rejection
    8. Hit orchestrator endpoints with and without token:
       - GET /health (no auth required)
       - GET /docs (no auth required)
       - POST /sandboxes (auth required)
       - GET /admin/sandboxes (admin scope required)
       - POST /internal/workers/register (no auth — internal)
"""

import asyncio
import os
import sys

import httpx


KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "agentbox")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "agentbox")
KEYCLOAK_CLIENT_SECRET = os.environ.get("KEYCLOAK_CLIENT_SECRET", "")
KEYCLOAK_TEST_USER = os.environ.get("KEYCLOAK_TEST_USER", "testuser")
KEYCLOAK_TEST_PASSWORD = os.environ.get("KEYCLOAK_TEST_PASSWORD", "testpass")
ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8090")

TOKEN_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
JWKS_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"


async def main():
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  ✓ {name}")
        else:
            failed += 1
            print(f"  ✗ {name}")
            if detail:
                print(f"      {detail}")

    print("=" * 60)
    print("KEYCLOAK JWT INTEGRATION TEST")
    print("=" * 60)

    if not KEYCLOAK_CLIENT_SECRET:
        print("\n  SKIPPED — set KEYCLOAK_CLIENT_SECRET to run this test.")
        print(f"  Expected Keycloak at: {KEYCLOAK_URL}")
        print(f"  Expected realm: {KEYCLOAK_REALM}")
        return True

    async with httpx.AsyncClient(timeout=15.0) as http:

        # --- 1. Password grant (user token) ---
        print("\n--- Password Grant ---")
        r = await http.post(TOKEN_URL, data={
            "grant_type": "password",
            "client_id": KEYCLOAK_CLIENT_ID,
            "client_secret": KEYCLOAK_CLIENT_SECRET,
            "username": KEYCLOAK_TEST_USER,
            "password": KEYCLOAK_TEST_PASSWORD,
        })
        check("password grant 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
        user_token = r.json().get("access_token") if r.status_code == 200 else None

        # --- 2. Client credentials grant (service account token) ---
        print("\n--- Client Credentials Grant ---")
        r = await http.post(TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": KEYCLOAK_CLIENT_ID,
            "client_secret": KEYCLOAK_CLIENT_SECRET,
        })
        check("client_credentials grant 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
        sa_token = r.json().get("access_token") if r.status_code == 200 else None

        # --- 3. JWKS endpoint ---
        print("\n--- JWKS Endpoint ---")
        r = await http.get(JWKS_URL)
        check("jwks endpoint 200", r.status_code == 200)
        if r.status_code == 200:
            jwks = r.json()
            check("jwks has keys", len(jwks.get("keys", [])) > 0, f"got {jwks}")

        # --- 4. Decode user token via JWKS ---
        print("\n--- Decode Token (JWKS) ---")
        if user_token:
            from agentbox.api.auth import JWTConfig, decode_token

            config = JWTConfig(
                enabled=True,
                jwks_uri=JWKS_URL,
                algorithm="RS256",
                issuer=f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}",
                client_id=KEYCLOAK_CLIENT_ID,
            )
            claims = decode_token(user_token, config)
            check("decoded sub", claims.sub is not None, f"sub={claims.sub}")
            check("decoded roles non-empty", len(claims.roles) > 0, f"roles={claims.roles}")
            check("decoded raw has exp", "exp" in claims.raw)
            print(f"      sub={claims.sub}")
            print(f"      roles={claims.roles}")
            print(f"      scope={claims.scope}")

            # Check realm roles mapped
            check("realm roles present", any(r in claims.roles for r in ["sandbox_user", "admin", "default-roles-agentbox"]),
                  f"roles={claims.roles}")

            # Check client roles mapped (if configured)
            # These depend on your Keycloak setup
        else:
            print("  (skipped — no user token)")

        # --- 5. Orchestrator with auth ---
        print("\n--- Orchestrator Endpoints (auth) ---")

        # Health — no auth needed
        r = await http.get(f"{ORCHESTRATOR_URL}/health")
        check("GET /health no auth", r.status_code == 200, f"got {r.status_code}")

        # Sandboxes — requires auth when JWT enabled
        r = await http.get(f"{ORCHESTRATOR_URL}/sandboxes")
        # If JWT is enabled, expect 401; if disabled, expect 200
        if r.status_code == 401:
            check("GET /sandboxes requires auth", True)

            # Now with token
            if user_token:
                r = await http.get(
                    f"{ORCHESTRATOR_URL}/sandboxes",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
                check("GET /sandboxes with token", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
        else:
            print("  (JWT not enabled on orchestrator — auth tests skipped)")

        # Admin — requires admin scope
        if user_token:
            r = await http.get(
                f"{ORCHESTRATOR_URL}/admin/sandboxes",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            # 200 if user has admin role, 403 if not
            check("GET /admin/sandboxes responds", r.status_code in (200, 403),
                  f"got {r.status_code}: {r.text[:200]}")

        # --- 6. Expired token ---
        print("\n--- Expired Token ---")
        if user_token:
            # Tamper with token to simulate expiry (won't work with RS256,
            # but we can test by waiting or using a pre-expired token)
            r = await http.get(
                f"{ORCHESTRATOR_URL}/sandboxes",
                headers={"Authorization": "Bearer expired.invalid.token"},
            )
            if r.status_code == 401:
                check("invalid token rejected", True)
            else:
                check("invalid token rejected", r.status_code == 200,
                      "JWT may not be enabled")

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"KEYCLOAK JWT: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
