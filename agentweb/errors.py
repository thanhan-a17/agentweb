"""Structured error types for AgentWeb.

All errors inherit from AgentWebError so callers can catch broadly,
then narrow on the type code for agent-native steering.
"""


class AgentWebError(Exception):
    """Base for all expected AgentWeb errors."""

    def __init__(self, message: str = "", *, code: str = "unknown") -> None:
        self.code = code
        super().__init__(message)


class RateLimited(AgentWebError):
    """Remote endpoint returned 429 or equivalent."""

    def __init__(self, message: str = "", *, retry_after: int = 10) -> None:
        super().__init__(message or "Rate limited by remote endpoint", code="rate_limited")
        self.retry_after = retry_after


class BotBlocked(AgentWebError):
    """Remote endpoint blocked the request as bot traffic."""

    def __init__(self, message: str = "", *, url: str = "") -> None:
        super().__init__(message or "Request blocked as bot traffic", code="bot_blocked")
        self.url = url


class Timeout(AgentWebError):
    """Request exceeded configured timeout."""

    def __init__(self, message: str = "", *, timeout: int = 0) -> None:
        super().__init__(message or f"Request timed out after {timeout}s", code="timeout")
        self.timeout = timeout


class NoResults(AgentWebError):
    """Search or fetch returned zero results."""

    def __init__(self, message: str = "", *, query: str = "") -> None:
        super().__init__(message or "No results found", code="no_results")
        self.query = query


class InvalidURL(AgentWebError):
    """URL failed validation."""

    def __init__(self, message: str = "", *, url: str = "") -> None:
        super().__init__(message or f"Invalid URL: {url}", code="invalid_url")
        self.url = url


class ValidationError(AgentWebError):
    """Input validation failed."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message, code="validation_error")


# ── Exception mapping helper ───────────────────────────────────────────


def map_exception(
    exc: Exception | None = None,
    *,
    status_code: int | None = None,
    url: str = "",
    query: str = "",
    timeout_val: int = 0,
) -> AgentWebError:
    """Map an exception and/or HTTP status code to a structured AgentWebError.

    Inspects both the exception type (preferred — most specific) and
    status code, then returns the appropriate error.

    Args:
        exc: The original exception (e.g. requests.Timeout, ValueError).
        status_code: HTTP response status code, if available.
        url: URL associated with the request (for BotBlocked, InvalidURL).
        query: Search query (for NoResults).
        timeout_val: Timeout value in seconds (for Timeout).

    Returns:
        An AgentWebError subclass instance.
    """
    # 1. Check if already a structured error.
    if isinstance(exc, AgentWebError):
        return exc

    # 2. Check status codes first (before exception type, since a 429
    #    may come with a vague exception but the status is definitive).
    if status_code is not None:
        if status_code == 429:
            return RateLimited(
                f"Rate limited (HTTP {status_code})",
                retry_after=10,
            )
        if status_code in (401, 403):
            return BotBlocked(
                f"Request blocked (HTTP {status_code})",
                url=url,
            )

    # 3. Check exception type.
    if exc is not None:
        exc_name = type(exc).__name__
        exc_mod = type(exc).__module__

        # requests library timeouts
        if isinstance(exc, TimeoutError):
            # Python built-in TimeoutError or requests.Timeout which inherits from it
            return Timeout(str(exc) or f"Request timed out after {timeout_val}s", timeout=timeout_val)

        if "timeout" in exc_name.lower() or "timeouterror" in exc_name.lower():
            return Timeout(str(exc) or f"Request timed out after {timeout_val}s", timeout=timeout_val)

        # Connection errors → BotBlocked (often firewall/blocking)
        if exc_name in ("ConnectionError", "ConnectTimeout", "ConnectionRefused"):
            # requests.exceptions.ConnectionError inherits from OSError, not our BotBlocked
            return BotBlocked(
                str(exc) or f"Connection failed — possible bot block: {url}",
                url=url,
            )

        # ValueError from _safe_url → InvalidURL
        if isinstance(exc, ValueError):
            msg = str(exc)
            if "url" in msg.lower() or "invalid" in msg.lower() or "unsupported" in msg.lower():
                return InvalidURL(msg, url=url)

        # Generic message-based fallback (same as _maybe_wrap in sdk.py)
        msg = str(exc or "").lower()
        if "rate" in msg or "429" in msg:
            return RateLimited(str(exc), retry_after=10)
        if "timeout" in msg or "timed out" in msg:
            return Timeout(str(exc), timeout=timeout_val)
        if "block" in msg or "denied" in msg or "403" in msg:
            return BotBlocked(str(exc), url=url)
        if "no result" in msg or "empty" in msg:
            return NoResults(str(exc), query=query)
        if "invalid" in msg or "unsupported" in msg:
            return InvalidURL(str(exc), url=url)

    # 4. Fallback — generic error.
    return AgentWebError(str(exc) if exc else f"Request failed (HTTP {status_code})", code="request_failed")
