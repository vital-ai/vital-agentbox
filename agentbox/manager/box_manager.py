import asyncio
import os
import time
import uuid
from enum import Enum

from agentbox.box.code_exec_box import CodeExecutorBox
from agentbox.box.git_box import GitBox


class SandboxState(str, Enum):
    WARMING = "warming"
    READY = "ready"
    EXECUTING = "executing"
    DESTROYED = "destroyed"


class SandboxInfo:
    """Metadata for a managed sandbox."""

    __slots__ = ("sandbox_id", "box", "state", "created_at", "last_used_at", "box_type")

    def __init__(self, sandbox_id, box, box_type="mem"):
        self.sandbox_id = sandbox_id
        self.box = box
        self.state = SandboxState.WARMING
        self.created_at = time.time()
        self.last_used_at = self.created_at
        self.box_type = box_type

    def touch(self):
        self.last_used_at = time.time()

    def to_dict(self):
        now = time.time()
        return {
            "sandbox_id": self.sandbox_id,
            "state": self.state.value,
            "box_type": self.box_type,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "age_seconds": round(now - self.created_at, 1),
            "idle_seconds": round(now - self.last_used_at, 1),
        }


class BoxManager:
    """Manages a pool of sandbox instances.

    Configuration (env vars):
        AGENTBOX_MAX_SANDBOXES      Max concurrent sandboxes (default: 50)
        AGENTBOX_IDLE_TIMEOUT       Seconds before idle sandbox is reaped (default: 300)
        AGENTBOX_MAX_LIFETIME       Max sandbox lifetime in seconds (default: 3600)
        AGENTBOX_EXEC_TIMEOUT       Per-execution timeout in seconds (default: 30)
        AGENTBOX_REAPER_INTERVAL    How often the reaper checks, in seconds (default: 30)
    """

    def __init__(self):
        self.max_sandboxes = int(os.environ.get("AGENTBOX_MAX_SANDBOXES", "50"))
        self.idle_timeout = int(os.environ.get("AGENTBOX_IDLE_TIMEOUT", "300"))
        self.max_lifetime = int(os.environ.get("AGENTBOX_MAX_LIFETIME", "3600"))
        self.exec_timeout = int(os.environ.get("AGENTBOX_EXEC_TIMEOUT", "30"))
        self._reaper_interval = int(os.environ.get("AGENTBOX_REAPER_INTERVAL", "30"))

        # sandbox_id → SandboxInfo
        self._sandboxes: dict[str, SandboxInfo] = {}
        self._lock = asyncio.Lock()
        self._reaper_task = None
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Start the manager and background reaper."""
        if self._started:
            return
        self._started = True
        self._reaper_task = asyncio.create_task(self._reaper_loop())

    async def stop(self):
        """Destroy all sandboxes and stop the reaper."""
        if not self._started:
            return
        self._started = False

        if self._reaper_task:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass
            self._reaper_task = None

        # Destroy all remaining sandboxes
        ids = list(self._sandboxes.keys())
        for sid in ids:
            await self._destroy_sandbox(sid)

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
        return False

    # ------------------------------------------------------------------
    # Sandbox CRUD
    # ------------------------------------------------------------------

    async def create_sandbox(self, sandbox_id=None, box_type="mem",
                             timeout=None, message_handler=None,
                             repo_id=None):
        """Create and start a new sandbox.

        Args:
            sandbox_id: Optional ID. Auto-generated if omitted.
            box_type: "mem" (default) or "git" (with isomorphic-git).
            timeout: Per-execution timeout override.
            message_handler: Custom sendMessage handler.
            repo_id: Repository ID for git box (enables push/pull sync).

        Returns:
            dict with sandbox_id and state.

        Raises:
            RuntimeError: If pool is at capacity.
        """
        async with self._lock:
            if len(self._sandboxes) >= self.max_sandboxes:
                raise RuntimeError(
                    f"Sandbox pool at capacity ({self.max_sandboxes}). "
                    "Destroy a sandbox first."
                )

            if sandbox_id is None:
                sandbox_id = str(uuid.uuid4())

            if sandbox_id in self._sandboxes:
                raise ValueError(f"Sandbox {sandbox_id!r} already exists.")

            if box_type == "git":
                box = GitBox(
                    repo_id=repo_id,
                    timeout=timeout or self.exec_timeout,
                    message_handler=message_handler,
                )
            else:
                box = CodeExecutorBox(
                    timeout=timeout or self.exec_timeout,
                    message_handler=message_handler,
                )
            info = SandboxInfo(sandbox_id, box, box_type=box_type)
            self._sandboxes[sandbox_id] = info

        # Start outside the lock (browser launch is slow)
        try:
            await box.start()
            info.state = SandboxState.READY
            info.touch()
        except Exception:
            async with self._lock:
                self._sandboxes.pop(sandbox_id, None)
            raise

        return info.to_dict()

    async def get_sandbox(self, sandbox_id):
        """Get sandbox metadata by ID. Returns None if not found."""
        info = self._sandboxes.get(sandbox_id)
        if info is None:
            return None
        return info.to_dict()

    async def list_sandboxes(self):
        """List all active sandboxes."""
        return [info.to_dict() for info in self._sandboxes.values()]

    async def destroy_sandbox(self, sandbox_id):
        """Destroy a sandbox by ID.

        Returns:
            True if destroyed, False if not found.
        """
        return await self._destroy_sandbox(sandbox_id)

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------

    async def run_code(self, sandbox_id, code, language="python"):
        """Run code in a sandbox. Returns result dict."""
        info = self._get_info(sandbox_id)
        info.state = SandboxState.EXECUTING
        info.touch()
        try:
            return await info.box.run_code(code, language=language)
        finally:
            if info.state == SandboxState.EXECUTING:
                info.state = SandboxState.READY

    async def run_shell(self, sandbox_id, command):
        """Run a shell command in a sandbox. Returns result dict."""
        info = self._get_info(sandbox_id)
        info.state = SandboxState.EXECUTING
        info.touch()
        try:
            return await info.box.run_shell(command)
        finally:
            if info.state == SandboxState.EXECUTING:
                info.state = SandboxState.READY

    async def read_file(self, sandbox_id, path):
        """Read a file from a sandbox."""
        info = self._get_info(sandbox_id)
        info.touch()
        return await info.box.read_file(path)

    async def write_file(self, sandbox_id, path, content):
        """Write a file in a sandbox."""
        info = self._get_info(sandbox_id)
        info.touch()
        return await info.box.write_file(path, content)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def metrics(self):
        """Return pool metrics dict."""
        states = {}
        for info in self._sandboxes.values():
            states[info.state.value] = states.get(info.state.value, 0) + 1

        return {
            "total": len(self._sandboxes),
            "max_sandboxes": self.max_sandboxes,
            "available": self.max_sandboxes - len(self._sandboxes),
            "by_state": states,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_info(self, sandbox_id):
        """Resolve sandbox_id → SandboxInfo or raise."""
        info = self._sandboxes.get(sandbox_id)
        if info is None:
            raise KeyError(f"Sandbox {sandbox_id!r} not found.")
        if info.state == SandboxState.DESTROYED:
            raise RuntimeError(f"Sandbox {sandbox_id!r} is destroyed.")
        return info

    async def _destroy_sandbox(self, sandbox_id):
        """Internal destroy — stops box, removes from pool."""
        async with self._lock:
            info = self._sandboxes.pop(sandbox_id, None)
        if info is None:
            return False
        info.state = SandboxState.DESTROYED
        try:
            await info.box.stop()
        except Exception:
            pass  # Best-effort cleanup
        return True

    async def _reaper_loop(self):
        """Background task that destroys idle or expired sandboxes."""
        while self._started:
            try:
                await asyncio.sleep(self._reaper_interval)
                await self._reap()
            except asyncio.CancelledError:
                break
            except Exception:
                pass  # Don't let reaper crash

    async def _reap(self):
        """Check all sandboxes for idle/lifetime expiry."""
        now = time.time()
        to_destroy = []

        for sid, info in list(self._sandboxes.items()):
            if info.state == SandboxState.DESTROYED:
                to_destroy.append(sid)
                continue

            age = now - info.created_at
            idle = now - info.last_used_at

            # Don't reap sandboxes that are warming up or executing
            if info.state in (SandboxState.WARMING, SandboxState.EXECUTING):
                continue

            if age > self.max_lifetime:
                to_destroy.append(sid)
            elif idle > self.idle_timeout:
                to_destroy.append(sid)

        for sid in to_destroy:
            await self._destroy_sandbox(sid)
