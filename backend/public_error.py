"""Public error values: stable code, the provider's message, retryable flag.

The provider's human-readable error message is forwarded so the user sees the
real reason; raw upstream bodies, request ids and credential-bearing details are
stripped. The owning layer logs the full diagnostic once.
"""

_SAFE_MESSAGES = {
    "auth": "sign-in required or the provider key was rejected",
    "rate_limited": "the provider rate limit was reached",
    "provider_balance": "the provider account has insufficient balance",
    "provider_unavailable": "the provider is unavailable",
    "network": "the connection to the provider failed",
    "internal": "the reply failed",
    "provider_error": "the provider reported a failure",
    "unknown": "the reply failed",
}


def classify(error) -> tuple[str, bool]:
    status = getattr(error, "status", None) or getattr(error, "status_code", None)
    if status in (401, 403):
        return "auth", False
    if status == 429:
        return "rate_limited", True
    if status == 402:
        return "provider_balance", False
    if isinstance(status, int) and 500 <= status < 600:
        return "provider_unavailable", True
    if isinstance(error, (TimeoutError, ConnectionError)):
        return "network", True
    return "internal", False


def _provider_message(error) -> str | None:
    # The SDK exception's .message is the provider's own reason; .body and .request_id hold the raw envelope we strip.
    message = getattr(error, "message", None)
    return message.strip() if isinstance(message, str) and message.strip() else None


def public_error(error, code: str | None = None, retryable: bool | None = None) -> dict:
    if isinstance(error, dict):
        resolved = error.get("code") or code or "unknown"
        message = str(error.get("message") or _SAFE_MESSAGES.get(resolved, _SAFE_MESSAGES["unknown"]))
        retry = error.get("retryable")
        if retry is None:
            retry = retryable
        return {"code": resolved, "message": message, "retryable": bool(retry)}
    if isinstance(error, BaseException):
        resolved, retry = classify(error)
        resolved = code or resolved
        if retryable is not None:
            retry = retryable
        message = _provider_message(error) or _SAFE_MESSAGES.get(resolved, _SAFE_MESSAGES["unknown"])
        return {"code": resolved, "message": message, "retryable": retry}
    # A bare string is an untrusted provider reason, not a safe message; never echo it.
    resolved = code or "provider_error"
    return {
        "code": resolved,
        "message": _SAFE_MESSAGES.get(resolved, _SAFE_MESSAGES["unknown"]),
        "retryable": bool(retryable),
    }


def error_frame(error, code: str | None = None, retryable: bool | None = None) -> dict:
    value = public_error(error, code, retryable)
    return {"error": value["message"], "code": value["code"], "retryable": value["retryable"]}
