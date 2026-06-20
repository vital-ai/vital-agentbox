"""
Unit tests for orchestrator browser routes and state extensions.

Tests the browser session routing, worker type filtering,
and REST endpoint behavior using mocked Redis state.
"""

import time
from unittest.mock import AsyncMock, patch

import pytest

from agentbox.orchestrator.state import OrchestratorState, WorkerInfo


# --- State extension tests ---

class TestWorkerInfoType:
    def test_code_worker(self):
        w = WorkerInfo(worker_id="w1", endpoint="http://w1:8000", type="code",
                       max_sandboxes=50, active_sandboxes=10)
        assert w.available == 40
        assert w.available_sessions == 0

    def test_browser_worker(self):
        w = WorkerInfo(worker_id="w1", endpoint="http://w1:8000", type="browser",
                       max_sandboxes=0, max_sessions=3, active_sessions=1)
        assert w.available == 0  # no sandboxes
        assert w.available_sessions == 2

    def test_both_worker(self):
        w = WorkerInfo(worker_id="w1", endpoint="http://w1:8000", type="both",
                       max_sandboxes=50, active_sandboxes=10,
                       max_sessions=3, active_sessions=1)
        assert w.available == 40
        assert w.available_sessions == 2


class TestPickWorker:
    @pytest.fixture
    def mock_redis(self):
        r = AsyncMock()
        r.smembers = AsyncMock(return_value={"w1", "w2", "w3"})
        return r

    def _make_state(self, redis_mock):
        return OrchestratorState(redis_mock)

    @pytest.mark.asyncio
    async def test_pick_code_worker(self, mock_redis):
        """pick_worker('code') should return code-capable worker with most slots."""
        state = self._make_state(mock_redis)

        workers = {
            "w1": {"worker_id": "w1", "endpoint": "http://w1:8000", "type": "code",
                   "max_sandboxes": "50", "active_sandboxes": "10",
                   "max_sessions": "0", "active_sessions": "0",
                   "state": "active", "last_heartbeat": str(time.time()),
                   "registered_at": str(time.time())},
            "w2": {"worker_id": "w2", "endpoint": "http://w2:8000", "type": "browser",
                   "max_sandboxes": "0", "active_sandboxes": "0",
                   "max_sessions": "3", "active_sessions": "0",
                   "state": "active", "last_heartbeat": str(time.time()),
                   "registered_at": str(time.time())},
            "w3": {"worker_id": "w3", "endpoint": "http://w3:8000", "type": "both",
                   "max_sandboxes": "30", "active_sandboxes": "5",
                   "max_sessions": "3", "active_sessions": "1",
                   "state": "active", "last_heartbeat": str(time.time()),
                   "registered_at": str(time.time())},
        }
        mock_redis.hgetall = AsyncMock(
            side_effect=lambda k: workers.get(k.split(":")[-1], {})
        )

        picked = await state.pick_worker(worker_type="code")
        # w1 has 40 available, w3 has 25 available, w2 is browser-only
        assert picked is not None
        assert picked.worker_id == "w1"

    @pytest.mark.asyncio
    async def test_pick_browser_worker(self, mock_redis):
        """pick_worker('browser') should return browser-capable worker with most sessions."""
        state = self._make_state(mock_redis)

        workers = {
            "w1": {"worker_id": "w1", "endpoint": "http://w1:8000", "type": "code",
                   "max_sandboxes": "50", "active_sandboxes": "10",
                   "max_sessions": "0", "active_sessions": "0",
                   "state": "active", "last_heartbeat": str(time.time()),
                   "registered_at": str(time.time())},
            "w2": {"worker_id": "w2", "endpoint": "http://w2:8000", "type": "browser",
                   "max_sandboxes": "0", "active_sandboxes": "0",
                   "max_sessions": "3", "active_sessions": "1",
                   "state": "active", "last_heartbeat": str(time.time()),
                   "registered_at": str(time.time())},
            "w3": {"worker_id": "w3", "endpoint": "http://w3:8000", "type": "both",
                   "max_sandboxes": "30", "active_sandboxes": "5",
                   "max_sessions": "5", "active_sessions": "0",
                   "state": "active", "last_heartbeat": str(time.time()),
                   "registered_at": str(time.time())},
        }
        mock_redis.hgetall = AsyncMock(
            side_effect=lambda k: workers.get(k.split(":")[-1], {})
        )

        picked = await state.pick_worker(worker_type="browser")
        # w2 has 2 available, w3 has 5 available, w1 is code-only
        assert picked is not None
        assert picked.worker_id == "w3"


class TestBrowserRoutes:
    @pytest.fixture
    def mock_redis(self):
        r = AsyncMock()
        return r

    @pytest.mark.asyncio
    async def test_set_and_get_browser_route(self, mock_redis):
        state = OrchestratorState(mock_redis)
        mock_redis.set = AsyncMock()
        mock_redis.get = AsyncMock(return_value="browser-1")

        await state.set_browser_route("session-abc", "browser-1")
        mock_redis.set.assert_awaited_once()

        worker_id = await state.get_browser_route("session-abc")
        assert worker_id == "browser-1"

    @pytest.mark.asyncio
    async def test_delete_browser_route(self, mock_redis):
        state = OrchestratorState(mock_redis)
        mock_redis.delete = AsyncMock()

        await state.delete_browser_route("session-abc")
        mock_redis.delete.assert_awaited_once()
