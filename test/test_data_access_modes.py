"""
Tests for S3 data access modes (Phase 1).

Covers:
- DataAccessMode enum + JWTConfig env var parsing
- _validate_data_path helper
- SandboxRecord with data_path/credential_expires_at (Redis round-trip)
- S3StorageBackend session_token + update_credentials
- Mode validation in create_sandbox route (via httpx TestClient)
"""

import asyncio
import json
import os
import time
import uuid
from unittest.mock import patch

import redis.asyncio as aioredis

from agentbox.api.auth import DataAccessMode, JWTConfig
from agentbox.orchestrator.state import OrchestratorState, SandboxRecord, WorkerInfo

REDIS_URL = "redis://localhost:6381"


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
    print("TEST: Data Access Modes (Phase 1)")
    print("=" * 60)

    # =================================================================
    # 1. DataAccessMode enum + JWTConfig
    # =================================================================
    print("\n--- DataAccessMode + JWTConfig ---")

    check("enum tenant value", DataAccessMode.TENANT == "tenant")
    check("enum path value", DataAccessMode.PATH == "path")
    check("enum path_credentials value", DataAccessMode.PATH_CREDENTIALS == "path_credentials")

    # Default (no env var set)
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AGENTBOX_DATA_ACCESS_MODE", None)
        config = JWTConfig.from_env()
        check("default mode is TENANT", config.data_access_mode == DataAccessMode.TENANT)

    # Explicit modes
    with patch.dict(os.environ, {"AGENTBOX_DATA_ACCESS_MODE": "path"}):
        config = JWTConfig.from_env()
        check("env path mode", config.data_access_mode == DataAccessMode.PATH)

    with patch.dict(os.environ, {"AGENTBOX_DATA_ACCESS_MODE": "path_credentials"}):
        config = JWTConfig.from_env()
        check("env path_credentials mode",
              config.data_access_mode == DataAccessMode.PATH_CREDENTIALS)

    with patch.dict(os.environ, {"AGENTBOX_DATA_ACCESS_MODE": "PATH"}):
        config = JWTConfig.from_env()
        check("case insensitive mode", config.data_access_mode == DataAccessMode.PATH)

    with patch.dict(os.environ, {"AGENTBOX_DATA_ACCESS_MODE": "invalid_mode"}):
        config = JWTConfig.from_env()
        check("invalid mode falls back to TENANT",
              config.data_access_mode == DataAccessMode.TENANT)

    # =================================================================
    # 2. _validate_data_path
    # =================================================================
    print("\n--- _validate_data_path ---")

    from agentbox.orchestrator.routes.sandboxes import _validate_data_path
    from fastapi import HTTPException

    # Valid paths
    result = _validate_data_path("org/project/data")
    check("valid data_path", result == "org/project/data", result)

    result = _validate_data_path("my-org/my-project")
    check("valid data_path with hyphens", result == "my-org/my-project", result)

    result = _validate_data_path("a/b/c/d/e")
    check("valid deep path", result == "a/b/c/d/e", result)

    # Invalid paths
    def expect_400(data_path, test_name):
        try:
            _validate_data_path(data_path)
            check(test_name, False, "expected HTTPException 400")
        except HTTPException as e:
            check(test_name, e.status_code == 400, f"got {e.status_code}: {e.detail}")
        except Exception as e:
            check(test_name, False, f"unexpected error: {e}")

    expect_400("", "empty data_path rejected")
    expect_400("/org/project", "leading slash rejected")
    expect_400("../escape", "path traversal rejected")
    expect_400("org/../escape", "embedded .. rejected")
    expect_400("org//double-slash", "double slash rejected")

    # =================================================================
    # 3. SandboxRecord with new fields (Redis round-trip)
    # =================================================================
    print("\n--- SandboxRecord with data_path/credential_expires_at ---")

    test_prefix = f"agentbox_test_{uuid.uuid4().hex[:8]}:"
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    await redis_client.ping()
    print(f"  (connected to Redis at {REDIS_URL}, prefix={test_prefix})")
    state = OrchestratorState(redis_client, prefix=test_prefix)

    # Mode 2: data_path set, no credential_expires_at
    rec_path = SandboxRecord(
        id="sb-path-001",
        worker_id="worker-1",
        box_type="git",
        repo_id=None,
        data_path="org/project/data",
        state="running",
        created_at=time.time(),
        last_active=time.time(),
        created_by="tenant-x",
    )
    await state.create_sandbox_record(rec_path)
    got = await state.get_sandbox_record("sb-path-001")
    check("data_path stored", got.data_path == "org/project/data", got.data_path)
    check("repo_id is None", got.repo_id is None, got.repo_id)
    check("credential_expires_at is None", got.credential_expires_at is None)
    check("created_by preserved", got.created_by == "tenant-x")

    # Mode 3: data_path + credential_expires_at + webhook metadata
    webhook_meta = {
        "credential_webhook_url": "https://example.com/webhook",
        "webhook_secret": "secret123",
    }
    rec_creds = SandboxRecord(
        id="sb-creds-002",
        worker_id="worker-1",
        box_type="git",
        data_path="client/project/workspace",
        state="running",
        created_at=time.time(),
        last_active=time.time(),
        created_by="tenant-y",
        credential_expires_at="2025-12-31T23:59:59Z",
        metadata=webhook_meta,
    )
    await state.create_sandbox_record(rec_creds)
    got = await state.get_sandbox_record("sb-creds-002")
    check("data_path with creds", got.data_path == "client/project/workspace",
          got.data_path)
    check("credential_expires_at stored",
          got.credential_expires_at == "2025-12-31T23:59:59Z",
          got.credential_expires_at)
    check("webhook metadata stored",
          got.metadata.get("credential_webhook_url") == "https://example.com/webhook",
          got.metadata)
    check("webhook secret in metadata",
          got.metadata.get("webhook_secret") == "secret123")

    # Mode 1: backward compatible (no data_path, no credential_expires_at)
    rec_tenant = SandboxRecord(
        id="sb-tenant-003",
        worker_id="worker-1",
        box_type="mem",
        repo_id="task-456",
        state="running",
        created_at=time.time(),
        last_active=time.time(),
        created_by="tenant-z",
    )
    await state.create_sandbox_record(rec_tenant)
    got = await state.get_sandbox_record("sb-tenant-003")
    check("backward compat: repo_id", got.repo_id == "task-456", got.repo_id)
    check("backward compat: data_path is None", got.data_path is None)
    check("backward compat: credential_expires_at is None",
          got.credential_expires_at is None)

    # =================================================================
    # 4. S3StorageBackend session_token + update_credentials
    # =================================================================
    print("\n--- S3StorageBackend session_token ---")

    try:
        from unittest.mock import MagicMock
        import boto3
        from agentbox.box.git.storage import S3StorageBackend

        # Test constructor with session_token
        with patch("boto3.client") as mock_client:
            backend = S3StorageBackend(
                bucket="test-bucket",
                prefix="repos/",
                access_key="AKIA_TEST",
                secret_key="secret_test",
                session_token="token_test",
                region_name="us-east-1",
            )
            call_kwargs = mock_client.call_args
            check("session_token passed to boto3",
                  call_kwargs[1].get("aws_session_token") == "token_test",
                  call_kwargs[1])
            check("access_key passed to boto3",
                  call_kwargs[1].get("aws_access_key_id") == "AKIA_TEST")
            check("secret_key passed to boto3",
                  call_kwargs[1].get("aws_secret_access_key") == "secret_test")
            check("region passed to boto3",
                  call_kwargs[1].get("region_name") == "us-east-1")

        # Test constructor without session_token
        with patch("boto3.client") as mock_client:
            backend = S3StorageBackend(
                bucket="test-bucket",
                access_key="AKIA_TEST",
                secret_key="secret_test",
            )
            call_kwargs = mock_client.call_args
            check("no session_token when not provided",
                  "aws_session_token" not in call_kwargs[1],
                  call_kwargs[1])

        # Test update_credentials
        with patch("boto3.client") as mock_client:
            backend = S3StorageBackend(
                bucket="test-bucket",
                access_key="old_key",
                secret_key="old_secret",
            )
            mock_client.reset_mock()
            backend.update_credentials(
                access_key="new_key",
                secret_key="new_secret",
                session_token="new_token",
                region_name="eu-west-1",
            )
            call_kwargs = mock_client.call_args
            check("update_credentials new key",
                  call_kwargs[1].get("aws_access_key_id") == "new_key")
            check("update_credentials new secret",
                  call_kwargs[1].get("aws_secret_access_key") == "new_secret")
            check("update_credentials new token",
                  call_kwargs[1].get("aws_session_token") == "new_token")
            check("update_credentials new region",
                  call_kwargs[1].get("region_name") == "eu-west-1")

    except ImportError:
        print("  (skipping S3StorageBackend tests — boto3 not installed)")

    # =================================================================
    # 5. _get_storage with s3_credentials
    # =================================================================
    print("\n--- _get_storage with s3_credentials ---")

    try:
        from agentbox.box.git_box import _get_storage

        creds = {
            "access_key_id": "AKIA_CALLER",
            "secret_access_key": "caller_secret",
            "session_token": "caller_token",
            "region": "ap-southeast-1",
            "endpoint_url": None,
        }

        with patch.dict(os.environ, {
            "AGENTBOX_GIT_STORE": "s3",
            "AGENTBOX_GIT_S3_BUCKET": "test-bucket",
        }):
            with patch("boto3.client") as mock_client:
                storage = _get_storage(s3_credentials=creds)
                check("_get_storage returns S3StorageBackend", storage is not None)
                call_kwargs = mock_client.call_args
                check("caller access_key used",
                      call_kwargs[1].get("aws_access_key_id") == "AKIA_CALLER")
                check("caller session_token used",
                      call_kwargs[1].get("aws_session_token") == "caller_token")

            # Without credentials, uses env vars
            with patch.dict(os.environ, {
                "AGENTBOX_GIT_S3_ACCESS_KEY": "ENV_KEY",
                "AGENTBOX_GIT_S3_SECRET_KEY": "ENV_SECRET",
            }):
                with patch("boto3.client") as mock_client:
                    storage = _get_storage(s3_credentials=None)
                    call_kwargs = mock_client.call_args
                    check("env access_key used when no creds",
                          call_kwargs[1].get("aws_access_key_id") == "ENV_KEY")
                    check("no session_token from env",
                          "aws_session_token" not in call_kwargs[1])
    except ImportError:
        print("  (skipping _get_storage tests — boto3 not installed)")

    # =================================================================
    # 6. _get_s3_credentials from shell env
    # =================================================================
    print("\n--- _get_s3_credentials ---")

    from agentbox.box.shell.host_commands.git_sync import _get_s3_credentials

    class MockEnv:
        def __init__(self, variables=None):
            self.variables = variables or {}

    # With valid creds in env
    creds_dict = {
        "access_key_id": "AKIA_SHELL",
        "secret_access_key": "shell_secret",
        "session_token": "shell_token",
    }
    env = MockEnv(variables={"AGENTBOX_S3_CREDENTIALS": json.dumps(creds_dict)})
    got_creds = _get_s3_credentials(env)
    check("creds extracted from env", got_creds is not None)
    check("access_key_id correct", got_creds["access_key_id"] == "AKIA_SHELL")
    check("session_token correct", got_creds["session_token"] == "shell_token")

    # Without creds
    env_empty = MockEnv()
    got_creds = _get_s3_credentials(env_empty)
    check("no creds returns None", got_creds is None)

    # Invalid JSON
    env_bad = MockEnv(variables={"AGENTBOX_S3_CREDENTIALS": "not-json"})
    got_creds = _get_s3_credentials(env_bad)
    check("invalid JSON returns None", got_creds is None)

    # =================================================================
    # 7. Phase 2: _parse_iso + _sign_payload
    # =================================================================
    print("\n--- Phase 2: _parse_iso + _sign_payload ---")

    from agentbox.orchestrator.credential_checker import _parse_iso, _sign_payload

    # _parse_iso
    ts = _parse_iso("2025-12-31T23:59:59Z")
    check("parse ISO Z suffix", ts == 1767225599.0, ts)

    ts2 = _parse_iso("2025-12-31T23:59:59+00:00")
    check("parse ISO +00:00", ts2 == 1767225599.0, ts2)

    ts3 = _parse_iso("invalid")
    check("parse invalid returns 0", ts3 == 0.0, ts3)

    ts4 = _parse_iso("")
    check("parse empty returns 0", ts4 == 0.0, ts4)

    # _sign_payload
    sig = _sign_payload(b'{"test": true}', "my-secret")
    check("sign_payload returns hex string", len(sig) == 64, sig)
    # Verify it's deterministic
    sig2 = _sign_payload(b'{"test": true}', "my-secret")
    check("sign_payload deterministic", sig == sig2)
    # Different secret → different signature
    sig3 = _sign_payload(b'{"test": true}', "other-secret")
    check("different secret → different sig", sig != sig3)

    # =================================================================
    # 8. Phase 2: update_credential_expiry (Redis)
    # =================================================================
    print("\n--- Phase 2: update_credential_expiry ---")

    # Create a sandbox with credentials
    rec_refresh = SandboxRecord(
        id="sb-refresh-001",
        worker_id="worker-1",
        box_type="git",
        data_path="org/project",
        state="running",
        created_at=time.time(),
        last_active=time.time(),
        created_by="tenant-r",
        credential_expires_at="2025-06-01T12:00:00Z",
    )
    await state.create_sandbox_record(rec_refresh)

    # Verify initial expiry
    got = await state.get_sandbox_record("sb-refresh-001")
    check("initial credential_expires_at",
          got.credential_expires_at == "2025-06-01T12:00:00Z")

    # Update expiry
    await state.update_credential_expiry("sb-refresh-001", "2025-07-01T12:00:00Z")
    got = await state.get_sandbox_record("sb-refresh-001")
    check("updated credential_expires_at",
          got.credential_expires_at == "2025-07-01T12:00:00Z",
          got.credential_expires_at)

    # =================================================================
    # 9. Phase 2: _check_credentials logic
    # =================================================================
    print("\n--- Phase 2: _check_credentials ---")

    from agentbox.orchestrator.credential_checker import _check_credentials
    from datetime import datetime, timezone, timedelta

    # Create a sandbox with credentials about to expire (within lead time)
    future_2min = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()
    rec_expiring = SandboxRecord(
        id="sb-expiring-001",
        worker_id="worker-1",
        box_type="git",
        data_path="org/soon",
        state="running",
        created_at=time.time(),
        last_active=time.time(),
        created_by="tenant-e",
        credential_expires_at=future_2min,
        metadata={"credential_webhook_url": "https://example.com/hook"},
    )
    await state.create_sandbox_record(rec_expiring)
    # Also set route so proxy doesn't 404
    await state.set_route("sb-expiring-001", "worker-1")

    notified = set()
    shutting_down = set()
    # The sandbox is within lead time (120s < 300s default), should be notified
    # (webhook will fail since URL isn't real, but we track notification)
    await _check_credentials(state, notified, shutting_down)
    check("expiring sandbox was notified", "sb-expiring-001" in notified,
          f"notified={notified}")

    # Create a sandbox that already expired
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    rec_expired = SandboxRecord(
        id="sb-expired-001",
        worker_id="worker-1",
        box_type="git",
        data_path="org/past",
        state="running",
        created_at=time.time(),
        last_active=time.time(),
        created_by="tenant-e",
        credential_expires_at=past,
    )
    await state.create_sandbox_record(rec_expired)
    await state.set_route("sb-expired-001", "worker-1")

    notified2 = set()
    shutting_down2 = set()
    await _check_credentials(state, notified2, shutting_down2)
    # Check the expired sandbox was destroyed
    got_expired = await state.get_sandbox_record("sb-expired-001")
    check("expired sandbox state is destroyed",
          got_expired.state == "destroyed", got_expired.state)

    # Create a sandbox far from expiry (should not be notified)
    future_1hr = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    rec_ok = SandboxRecord(
        id="sb-ok-001",
        worker_id="worker-1",
        box_type="git",
        data_path="org/ok",
        state="running",
        created_at=time.time(),
        last_active=time.time(),
        created_by="tenant-e",
        credential_expires_at=future_1hr,
    )
    await state.create_sandbox_record(rec_ok)
    notified3 = set()
    shutting_down3 = set()
    await _check_credentials(state, notified3, shutting_down3)
    check("non-expiring sandbox not notified", "sb-ok-001" not in notified3)

    # =================================================================
    # 10. Phase 2: UpdateCredentialsRequest model
    # =================================================================
    print("\n--- Phase 2: UpdateCredentialsRequest ---")

    from agentbox.orchestrator.routes.sandboxes import UpdateCredentialsRequest, S3Credentials

    # Valid request
    ucr = UpdateCredentialsRequest(
        s3_credentials=S3Credentials(
            access_key_id="ASIA_NEW",
            secret_access_key="new_secret",
            session_token="new_token",
            expiration="2025-12-31T23:59:59Z",
        )
    )
    check("UpdateCredentialsRequest valid",
          ucr.s3_credentials.access_key_id == "ASIA_NEW")
    check("UpdateCredentialsRequest expiration",
          ucr.s3_credentials.expiration == "2025-12-31T23:59:59Z")

    # Missing s3_credentials should fail
    from pydantic import ValidationError
    try:
        UpdateCredentialsRequest()
        check("UpdateCredentialsRequest requires s3_credentials", False)
    except ValidationError:
        check("UpdateCredentialsRequest requires s3_credentials", True)

    # =================================================================
    # 11. Phase 2: PATCH proxy support
    # =================================================================
    print("\n--- Phase 2: proxy PATCH support ---")

    from agentbox.orchestrator.proxy import proxy_to_worker
    # Verify PATCH is in the proxy (we can't easily test the full proxy
    # without a running worker, but we can verify the code path exists)
    import inspect
    source = inspect.getsource(proxy_to_worker)
    check("proxy supports PATCH", 'method == "PATCH"' in source)

    # =================================================================
    # Cleanup
    # =================================================================
    cursor = 0
    while True:
        cursor, keys = await redis_client.scan(cursor, match=f"{test_prefix}*", count=200)
        if keys:
            await redis_client.delete(*keys)
        if cursor == 0:
            break
    print(f"\n  (cleaned up test keys with prefix {test_prefix})")
    await redis_client.aclose()

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
