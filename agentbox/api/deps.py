"""Dependency injection for the FastAPI app."""

from agentbox.manager.box_manager import BoxManager

# Singleton BoxManager instance — initialized during app lifespan
_manager: BoxManager | None = None


def get_manager() -> BoxManager:
    """FastAPI dependency that returns the BoxManager singleton."""
    if _manager is None:
        raise RuntimeError("BoxManager not initialized. App lifespan not started.")
    return _manager


def set_manager(manager: BoxManager):
    """Set the global BoxManager instance (called during lifespan startup)."""
    global _manager
    _manager = manager


def clear_manager():
    """Clear the global BoxManager instance (called during lifespan shutdown)."""
    global _manager
    _manager = None
