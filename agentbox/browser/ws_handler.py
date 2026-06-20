"""
WebSocket message handler — dispatches BrowserCommands to a BrowserSession.
"""

from __future__ import annotations

import logging

from agentbox.browser.session import BrowserSession
from agentbox.browser.models import BrowserAction, BrowserCommand, BrowserResponse, PageState, ResponseStatus

log = logging.getLogger(__name__)


async def handle_command(session: BrowserSession, command: BrowserCommand, send_progress=None) -> BrowserResponse:
    """Execute a browser command against a session and return the response.

    Args:
        session: The browser session to execute the command against.
        command: The command to execute.
        send_progress: Optional async callback(message: str) for
                       streaming progress updates during long-running commands.
    """
    action = command.action
    try:
        match action:
            case BrowserAction.NAVIGATE:
                if not command.url:
                    return _error(action, "url is required")
                title = await session.navigate(
                    command.url,
                    wait_until=command.wait_until or "domcontentloaded",
                    timeout=command.timeout or 60000,
                )
                return await _ok(session, action, title)

            case BrowserAction.FILL:
                if not command.selector or command.value is None:
                    return _error(action, "selector and value are required")
                await session.fill(command.selector, command.value)
                return await _ok(session, action)

            case BrowserAction.CLICK:
                if not command.selector:
                    return _error(action, "selector is required")
                await session.click(command.selector)
                return await _ok(session, action)

            case BrowserAction.SELECT:
                if not command.selector or command.value is None:
                    return _error(action, "selector and value are required")
                await session.select(command.selector, command.value)
                return await _ok(session, action)

            case BrowserAction.GET_CONTENT:
                html = await session.get_content()
                return await _ok(session, action, html)

            case BrowserAction.GET_TITLE:
                title = await session.get_title()
                return await _ok(session, action, title)

            case BrowserAction.GET_URL:
                url = await session.get_url()
                return await _ok(session, action, url)

            case BrowserAction.WAIT:
                ms = command.timeout or 1000
                await session.wait(ms)
                return await _ok(session, action)

            case BrowserAction.WAIT_FOR_SELECTOR:
                if not command.selector:
                    return _error(action, "selector is required")
                found = await session.wait_for_selector(
                    command.selector, timeout=command.timeout or 30000
                )
                return await _ok(session, action, found)

            case BrowserAction.WAIT_FOR_LOAD_STATE:
                state = command.state or "networkidle"
                await session.wait_for_load_state(state, timeout=command.timeout or 10000)
                return await _ok(session, action)

            case BrowserAction.CLICK_AND_WAIT:
                if not command.selector:
                    return _error(action, "selector is required")
                title = await session.click_and_wait_for_navigation(
                    command.selector,
                    wait_until=command.wait_until or "domcontentloaded",
                    timeout=command.timeout or 30000,
                )
                return await _ok(session, action, title)

            case BrowserAction.SOLVE_CAPTCHA:
                result = await session.solve_captcha(on_progress=send_progress)
                return await _ok(session, action, result)

            case BrowserAction.SCREENSHOT:
                b64 = await session.screenshot()
                return await _ok(session, action, b64)

            case BrowserAction.EVALUATE:
                if not command.expression:
                    return _error(action, "expression is required")
                result = await session.evaluate(command.expression)
                return await _ok(session, action, result)

            case BrowserAction.CLOSE:
                return BrowserResponse(status=ResponseStatus.OK, action="close", data="close_requested")

            case _:
                return _error(action, f"Unknown action: {action}")

    except Exception as exc:
        log.error("[%s] Command %s failed: %s", session.session_id, action, exc, exc_info=True)
        return _error(action, str(exc))


async def _ok(session: BrowserSession, action: BrowserAction | str, data=None) -> BrowserResponse:
    page_state = await session.get_page_state()
    return BrowserResponse(
        status=ResponseStatus.OK,
        action=str(action),
        data=data,
        page=PageState(**page_state),
    )


def _error(action: BrowserAction | str, message: str) -> BrowserResponse:
    return BrowserResponse(status=ResponseStatus.ERROR, action=str(action), message=message)
