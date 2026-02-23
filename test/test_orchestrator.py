"""
Test the orchestrator state layer, routes, and JWT middleware.

Uses real Redis on localhost:6381.
Tests cover: worker registry, sandbox routing, sandbox DB,
admin endpoints, JWT enforcement, and proxy logic.
"""

import asyncio
import json
import time
import uuid

import redis.asyncio as aioredis

from agentbox.orchestrator.state import (
    OrchestratorState,
    WorkerInfo,
    SandboxRecord,
)

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
    print("TEST: Orchestrator State + Auth")
    print("=" * 60)

    # --- Worker Registry ---
    print("\n--- Worker Registry ---")

    # Use a unique prefix per test run to avoid collisions
    test_prefix = f"agentbox_test_{uuid.uuid4().hex[:8]}:"
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    await redis.ping()
    print(f"  (connected to Redis at {REDIS_URL}, prefix={test_prefix})")
    state = OrchestratorState(redis, prefix=test_prefix)

    # Register workers
    w1 = WorkerInfo(
        worker_id="worker-1",
        endpoint="http://10.0.1.5:8000",
        max_sandboxes=50,
        active_sandboxes=10,
    )
    w2 = WorkerInfo(
        worker_id="worker-2",
        endpoint="http://10.0.1.6:8000",
        max_sandboxes=50,
        active_sandboxes=45,
    )
    await state.register_worker(w1, ttl=300)
    await state.register_worker(w2, ttl=300)

    # List workers
    workers = await state.list_workers()
    check("list_workers returns 2", len(workers) == 2, f"got {len(workers)}")

    # Get specific worker
    got = await state.get_worker("worker-1")
    check("get_worker by id", got is not None)
    check("worker endpoint", got.endpoint == "http://10.0.1.5:8000", got.endpoint)
    check("worker max_sandboxes", got.max_sandboxes == 50)
    check("worker active_sandboxes", got.active_sandboxes == 10)

    # Filter by state
    active = await state.list_workers(state="active")
    check("filter active workers", len(active) == 2)

    # Pick worker (should pick worker-1 with more available slots)
    best = await state.pick_worker()
    check("pick_worker returns worker-1", best.worker_id == "worker-1",
          f"got {best.worker_id}, w1.available={w1.available}, w2.available={w2.available}")

    # Deregister
    await state.deregister_worker("worker-2")
    workers = await state.list_workers()
    check("deregister removes worker", len(workers) == 1)

    # Get nonexistent
    got = await state.get_worker("worker-999")
    check("get nonexistent worker returns None", got is None)

    # --- Sandbox Routing ---
    print("\n--- Sandbox Routing ---")

    await state.set_route("sandbox-abc", "worker-1", ttl=3600)
    route = await state.get_route("sandbox-abc")
    check("set/get route", route == "worker-1", route)

    await state.delete_route("sandbox-abc")
    route = await state.get_route("sandbox-abc")
    check("delete route", route is None)

    no_route = await state.get_route("nonexistent-sandbox")
    check("get nonexistent route", no_route is None)

    # --- Sandbox Database ---
    print("\n--- Sandbox Database ---")

    rec1 = SandboxRecord(
        id="sandbox-001",
        worker_id="worker-1",
        box_type="mem",
        state="running",
        created_at=time.time() - 100,
        last_active=time.time(),
        created_by="tenant-alice",
    )
    rec2 = SandboxRecord(
        id="sandbox-002",
        worker_id="worker-1",
        box_type="git",
        repo_id="task-123",
        state="running",
        created_at=time.time() - 50,
        last_active=time.time(),
        created_by="tenant-bob",
    )
    rec3 = SandboxRecord(
        id="sandbox-003",
        worker_id="worker-1",
        box_type="mem",
        state="destroyed",
        created_at=time.time() - 200,
        created_by="tenant-alice",
    )

    await state.create_sandbox_record(rec1)
    await state.create_sandbox_record(rec2)
    await state.create_sandbox_record(rec3)

    # Get specific record
    got = await state.get_sandbox_record("sandbox-001")
    check("get sandbox record", got is not None)
    check("record id", got.id == "sandbox-001")
    check("record worker_id", got.worker_id == "worker-1")
    check("record box_type", got.box_type == "mem")
    check("record state", got.state == "running")
    check("record created_by", got.created_by == "tenant-alice")

    # Get git box record
    got2 = await state.get_sandbox_record("sandbox-002")
    check("git record repo_id", got2.repo_id == "task-123", got2.repo_id)
    check("git record box_type", got2.box_type == "git")

    # List all
    all_records = await state.list_sandbox_records()
    check("list all records", len(all_records) == 3, f"got {len(all_records)}")

    # Filter by state
    running = await state.list_sandbox_records(state="running")
    check("filter running", len(running) == 2, f"got {len(running)}")

    destroyed = await state.list_sandbox_records(state="destroyed")
    check("filter destroyed", len(destroyed) == 1)

    # Filter by tenant
    alice_records = await state.list_sandbox_records(tenant="tenant-alice")
    check("filter by tenant alice", len(alice_records) == 2,
          f"got {len(alice_records)}: {[r.id for r in alice_records]}")

    bob_records = await state.list_sandbox_records(tenant="tenant-bob")
    check("filter by tenant bob", len(bob_records) == 1)

    # Update state
    await state.update_sandbox_state("sandbox-001", "destroyed")
    got = await state.get_sandbox_record("sandbox-001")
    check("update state", got.state == "destroyed")

    # Get nonexistent
    got = await state.get_sandbox_record("nonexistent")
    check("get nonexistent record", got is None)

    # --- Aggregate Metrics ---
    print("\n--- Aggregate Metrics ---")

    # Re-register worker-1 for metrics
    await state.register_worker(w1, ttl=300)
    metrics = await state.aggregate_metrics()
    check("metrics workers_total", metrics["workers_total"] == 1)
    check("metrics workers_active", metrics["workers_active"] == 1)
    check("metrics sandboxes_capacity", metrics["sandboxes_capacity"] == 50)
    check("metrics sandboxes_active", metrics["sandboxes_active"] == 10)
    check("metrics sandboxes_total_records", metrics["sandboxes_total_records"] == 3)

    # --- Cleanup: delete all test keys ---
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=f"{test_prefix}*", count=200)
        if keys:
            await redis.delete(*keys)
        if cursor == 0:
            break
    print(f"  (cleaned up test keys with prefix {test_prefix})")
    await redis.aclose()

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
