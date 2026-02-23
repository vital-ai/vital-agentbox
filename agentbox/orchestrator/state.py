"""
Redis-backed shared state for the orchestrator.

Manages three data structures:
1. Worker registry — worker_id → {endpoint, capacity, state, last_heartbeat}
2. Sandbox routing table — sandbox_id → worker_id (for request proxying)
3. Sandbox database — sandbox_id → full metadata (lifecycle, tenant, type)

Redis Cluster / AWS MemoryDB compatibility:
- Every public method issues only single-key Redis commands. No multi-key
  operations (MGET, MSET, SUNION, etc.) are used, so keys can live in
  different hash slots without issue.
- Methods that touch multiple keys (e.g. register_worker writes a hash
  AND updates a set) do so with separate single-key commands. These are
  not atomic across keys, which is acceptable — eventual consistency is
  fine for the worker registry and index sets.
- No KEYS, SCAN, FLUSHDB, or other cluster-unfriendly commands.
- Compatible with redis-py RedisCluster (redis.asyncio.RedisCluster)
  and standalone Redis (redis.asyncio.Redis).
"""

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class WorkerInfo:
    worker_id: str
    endpoint: str  # e.g. "http://10.0.1.5:8000"
    max_sandboxes: int = 50
    active_sandboxes: int = 0
    state: str = "active"  # active, draining, dead
    last_heartbeat: float = 0.0
    registered_at: float = 0.0

    @property
    def available(self) -> int:
        return max(0, self.max_sandboxes - self.active_sandboxes)


@dataclass
class SandboxRecord:
    id: str
    worker_id: str
    box_type: str = "mem"  # mem, git
    repo_id: Optional[str] = None
    state: str = "running"  # running, idle, destroyed
    created_at: float = 0.0
    last_active: float = 0.0
    created_by: Optional[str] = None  # tenant from JWT sub
    metadata: dict = field(default_factory=dict)


class OrchestratorState:
    """Redis-backed shared state for orchestrator instances.

    All orchestrator instances share the same Redis, so any instance
    can handle any request. State is structured as:

        agentbox:worker:{worker_id}         → hash (WorkerInfo fields)
        agentbox:workers:index              → set of worker_ids
        agentbox:route:{sandbox_id}         → worker_id (string, with TTL)
        agentbox:sandbox:{sandbox_id}       → hash (SandboxRecord fields)
        agentbox:sandboxes:index            → sorted set (score = created_at)
        agentbox:sandboxes:by_tenant:{tid}  → set of sandbox_ids
    """

    def __init__(self, redis_client, prefix: str = "agentbox:"):
        self._redis = redis_client
        self._prefix = prefix

    def _key(self, *parts) -> str:
        return self._prefix + ":".join(parts)

    # ------------------------------------------------------------------
    # Worker Registry
    # ------------------------------------------------------------------

    async def register_worker(self, info: WorkerInfo, ttl: int = 60) -> None:
        """Register or update a worker. TTL acts as liveness timeout."""
        key = self._key("worker", info.worker_id)
        data = asdict(info)
        data["last_heartbeat"] = time.time()
        if not info.registered_at:
            data["registered_at"] = time.time()
        # Store metadata as JSON string
        await self._redis.hset(key, mapping={k: json.dumps(v) if isinstance(v, dict) else str(v) for k, v in data.items()})
        await self._redis.expire(key, ttl)
        # Add to index
        await self._redis.sadd(self._key("workers", "index"), info.worker_id)

    async def deregister_worker(self, worker_id: str) -> None:
        """Remove a worker from the registry."""
        await self._redis.delete(self._key("worker", worker_id))
        await self._redis.srem(self._key("workers", "index"), worker_id)

    async def get_worker(self, worker_id: str) -> Optional[WorkerInfo]:
        """Get worker info. Returns None if not found or expired."""
        data = await self._redis.hgetall(self._key("worker", worker_id))
        if not data:
            return None
        return WorkerInfo(
            worker_id=data.get("worker_id", worker_id),
            endpoint=data.get("endpoint", ""),
            max_sandboxes=int(data.get("max_sandboxes", 50)),
            active_sandboxes=int(data.get("active_sandboxes", 0)),
            state=data.get("state", "active"),
            last_heartbeat=float(data.get("last_heartbeat", 0)),
            registered_at=float(data.get("registered_at", 0)),
        )

    async def list_workers(self, state: Optional[str] = None) -> list[WorkerInfo]:
        """List all registered workers, optionally filtered by state."""
        worker_ids = await self._redis.smembers(self._key("workers", "index"))
        workers = []
        for wid in worker_ids:
            w = await self.get_worker(wid)
            if w is None:
                # Expired — clean up index
                await self._redis.srem(self._key("workers", "index"), wid)
                continue
            if state and w.state != state:
                continue
            workers.append(w)
        return workers

    async def pick_worker(self) -> Optional[WorkerInfo]:
        """Pick the active worker with the most available slots."""
        workers = await self.list_workers(state="active")
        if not workers:
            return None
        return max(workers, key=lambda w: w.available)

    # ------------------------------------------------------------------
    # Sandbox Routing Table
    # ------------------------------------------------------------------

    async def set_route(self, sandbox_id: str, worker_id: str, ttl: int = 3600) -> None:
        """Map sandbox_id → worker_id for request routing."""
        await self._redis.set(self._key("route", sandbox_id), worker_id, ex=ttl)

    async def get_route(self, sandbox_id: str) -> Optional[str]:
        """Look up which worker owns a sandbox."""
        return await self._redis.get(self._key("route", sandbox_id))

    async def delete_route(self, sandbox_id: str) -> None:
        """Remove a sandbox route (after destruction)."""
        await self._redis.delete(self._key("route", sandbox_id))

    # ------------------------------------------------------------------
    # Sandbox Database
    # ------------------------------------------------------------------

    async def create_sandbox_record(self, record: SandboxRecord) -> None:
        """Store a sandbox record and update indexes."""
        key = self._key("sandbox", record.id)
        data = {
            "id": record.id,
            "worker_id": record.worker_id,
            "box_type": record.box_type,
            "repo_id": record.repo_id or "",
            "state": record.state,
            "created_at": str(record.created_at or time.time()),
            "last_active": str(record.last_active or time.time()),
            "created_by": record.created_by or "",
            "metadata": json.dumps(record.metadata),
        }
        await self._redis.hset(key, mapping=data)
        # Sorted set index (score = created_at)
        await self._redis.zadd(
            self._key("sandboxes", "index"),
            {record.id: float(data["created_at"])},
        )
        # Per-tenant index
        if record.created_by:
            await self._redis.sadd(
                self._key("sandboxes", "by_tenant", record.created_by),
                record.id,
            )

    async def get_sandbox_record(self, sandbox_id: str) -> Optional[SandboxRecord]:
        """Get full sandbox metadata."""
        data = await self._redis.hgetall(self._key("sandbox", sandbox_id))
        if not data:
            return None
        return SandboxRecord(
            id=data.get("id", sandbox_id),
            worker_id=data.get("worker_id", ""),
            box_type=data.get("box_type", "mem"),
            repo_id=data.get("repo_id") or None,
            state=data.get("state", "running"),
            created_at=float(data.get("created_at", 0)),
            last_active=float(data.get("last_active", 0)),
            created_by=data.get("created_by") or None,
            metadata=json.loads(data.get("metadata", "{}")),
        )

    async def update_sandbox_state(self, sandbox_id: str, state: str) -> None:
        """Update sandbox state (e.g., running → destroyed).

        Uses a single HSET with mapping to update both fields atomically
        on the same key (cluster-safe: single key per command).
        """
        key = self._key("sandbox", sandbox_id)
        await self._redis.hset(key, mapping={
            "state": state,
            "last_active": str(time.time()),
        })

    async def list_sandbox_records(
        self,
        state: Optional[str] = None,
        tenant: Optional[str] = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[SandboxRecord]:
        """List sandbox records with optional filters."""
        if tenant:
            # Use per-tenant index
            sandbox_ids = await self._redis.smembers(
                self._key("sandboxes", "by_tenant", tenant)
            )
            sandbox_ids = sorted(sandbox_ids)
        else:
            # Use sorted set index (newest first)
            sandbox_ids = await self._redis.zrevrange(
                self._key("sandboxes", "index"), offset, offset + limit - 1,
            )

        records = []
        for sid in sandbox_ids:
            rec = await self.get_sandbox_record(sid)
            if rec is None:
                continue
            if state and rec.state != state:
                continue
            records.append(rec)

        # Apply offset/limit for tenant-filtered results
        if tenant:
            records = records[offset:offset + limit]

        return records

    # ------------------------------------------------------------------
    # Aggregate Metrics
    # ------------------------------------------------------------------

    async def aggregate_metrics(self) -> dict:
        """Aggregate metrics across all workers."""
        workers = await self.list_workers()
        total_capacity = sum(w.max_sandboxes for w in workers)
        total_active = sum(w.active_sandboxes for w in workers)
        total_available = sum(w.available for w in workers)

        # Count sandbox records by state
        all_ids = await self._redis.zcard(self._key("sandboxes", "index"))

        return {
            "workers_total": len(workers),
            "workers_active": len([w for w in workers if w.state == "active"]),
            "workers_draining": len([w for w in workers if w.state == "draining"]),
            "sandboxes_capacity": total_capacity,
            "sandboxes_active": total_active,
            "sandboxes_available": total_available,
            "sandboxes_total_records": all_ids,
        }
