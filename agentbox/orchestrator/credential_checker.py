"""
Background task that monitors credential expiry for Mode 3 sandboxes.

Runs as an asyncio task inside the orchestrator. Periodically scans all
running sandboxes for upcoming credential expiry, fires webhooks to notify
the caller, and initiates graceful shutdown if credentials are not refreshed.

Timeline per sandbox:
  expires_at - lead_time  → fire webhook (credentials_expiring)
  expires_at - grace_period → begin graceful shutdown if no PATCH received
  expires_at              → credentials expire, sandbox destroyed
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone

import httpx

from agentbox.orchestrator.state import OrchestratorState

logger = logging.getLogger(__name__)

# Configurable timings (seconds)
LEAD_TIME = int(os.environ.get("AGENTBOX_CREDENTIAL_EXPIRY_LEAD_TIME", "300"))  # 5 min
GRACE_PERIOD = int(os.environ.get("AGENTBOX_CREDENTIAL_GRACE_PERIOD", "60"))  # 1 min
CHECK_INTERVAL = int(os.environ.get("AGENTBOX_CREDENTIAL_CHECK_INTERVAL", "30"))  # 30s


def _parse_iso(ts: str) -> float:
    """Parse ISO 8601 timestamp to Unix epoch seconds."""
    try:
        # Handle both 'Z' suffix and +00:00
        ts = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, AttributeError):
        return 0.0


def _sign_payload(payload: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature for webhook payload."""
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


async def _fire_webhook(
    webhook_url: str,
    webhook_secret: str | None,
    sandbox_id: str,
    data_path: str | None,
    expires_at: str,
    expires_in_seconds: int,
) -> bool:
    """Send a credential_expiring webhook to the caller.

    Returns True if the webhook was delivered successfully (2xx).
    """
    payload = {
        "event": "credentials_expiring",
        "sandbox_id": sandbox_id,
        "data_path": data_path,
        "expires_at": expires_at,
        "expires_in_seconds": expires_in_seconds,
    }
    body = json.dumps(payload).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if webhook_secret:
        sig = _sign_payload(body, webhook_secret)
        headers["X-AgentBox-Signature"] = f"sha256={sig}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, content=body, headers=headers)
        if resp.status_code < 300:
            logger.info("Webhook delivered for sandbox %s (status=%d)", sandbox_id, resp.status_code)
            return True
        else:
            logger.warning("Webhook failed for sandbox %s (status=%d, body=%s)",
                           sandbox_id, resp.status_code, resp.text[:200])
            return False
    except Exception as e:
        logger.warning("Webhook error for sandbox %s: %s", sandbox_id, e)
        return False


async def credential_check_loop(state: OrchestratorState):
    """Background loop that checks credential expiry and fires webhooks.

    This runs inside the orchestrator's lifespan. It scans all running
    sandboxes with credential_expires_at set and takes action based on
    the timeline.
    """
    # Track which sandboxes we've already notified to avoid duplicate webhooks
    notified: set[str] = set()
    # Track which sandboxes we've started graceful shutdown for
    shutting_down: set[str] = set()

    while True:
        try:
            await asyncio.sleep(CHECK_INTERVAL)
            await _check_credentials(state, notified, shutting_down)
        except asyncio.CancelledError:
            logger.info("Credential checker shutting down")
            break
        except Exception:
            logger.exception("Credential checker error (will retry)")


async def _check_credentials(
    state: OrchestratorState,
    notified: set[str],
    shutting_down: set[str],
):
    """Single pass: check all running sandboxes for credential expiry."""
    records = await state.list_sandbox_records(state="running")
    now = time.time()

    for rec in records:
        if not rec.credential_expires_at:
            continue

        expires_epoch = _parse_iso(rec.credential_expires_at)
        if expires_epoch <= 0:
            continue

        seconds_until_expiry = expires_epoch - now

        # Already expired → destroy
        if seconds_until_expiry <= 0:
            logger.warning("Credentials expired for sandbox %s — destroying", rec.id)
            await state.update_sandbox_state(rec.id, "destroyed")
            await state.delete_route(rec.id)
            notified.discard(rec.id)
            shutting_down.discard(rec.id)
            continue

        # Within grace period → graceful shutdown
        if seconds_until_expiry <= GRACE_PERIOD and rec.id not in shutting_down:
            logger.warning(
                "Credentials expiring in %ds for sandbox %s — initiating graceful shutdown",
                int(seconds_until_expiry), rec.id,
            )
            shutting_down.add(rec.id)
            # Try to trigger a sync/push before destroying
            try:
                from agentbox.orchestrator.proxy import proxy_to_worker
                await proxy_to_worker(state, rec.id, "DELETE", "", timeout=30.0)
            except Exception:
                pass  # Best-effort
            await state.update_sandbox_state(rec.id, "destroyed")
            await state.delete_route(rec.id)
            notified.discard(rec.id)
            continue

        # Within lead time → fire webhook
        if seconds_until_expiry <= LEAD_TIME and rec.id not in notified:
            webhook_url = rec.metadata.get("credential_webhook_url")
            webhook_secret = rec.metadata.get("webhook_secret")
            if webhook_url:
                success = await _fire_webhook(
                    webhook_url=webhook_url,
                    webhook_secret=webhook_secret,
                    sandbox_id=rec.id,
                    data_path=rec.data_path,
                    expires_at=rec.credential_expires_at,
                    expires_in_seconds=int(seconds_until_expiry),
                )
                notified.add(rec.id)
                if not success:
                    # Retry once
                    await asyncio.sleep(2)
                    await _fire_webhook(
                        webhook_url=webhook_url,
                        webhook_secret=webhook_secret,
                        sandbox_id=rec.id,
                        data_path=rec.data_path,
                        expires_at=rec.credential_expires_at,
                        expires_in_seconds=int(seconds_until_expiry - 2),
                    )
            else:
                # No webhook configured — just log
                logger.info(
                    "Credentials expiring in %ds for sandbox %s (no webhook configured)",
                    int(seconds_until_expiry), rec.id,
                )
                notified.add(rec.id)
