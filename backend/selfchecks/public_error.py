"""Public error values keep a stable code and never leak raw exception text."""

from public_error import classify, error_frame, public_error


class UpstreamError(Exception):
    status = 503


def main():
    sentinel = "SENTINEL-UPSTREAM-BODY detail"
    value = public_error(UpstreamError(sentinel))
    assert value["code"] == "provider_unavailable", value
    assert value["retryable"] is True, value
    assert sentinel not in value["message"], "raw exception text must not reach the public message"

    assert classify(TimeoutError("x")) == ("network", True)
    assert public_error(TimeoutError("x"))["code"] == "network"

    class BalanceError(Exception):
        status = 402

    balance = public_error(BalanceError(sentinel))
    assert balance["code"] == "provider_balance", balance
    assert balance["retryable"] is False
    assert sentinel not in balance["message"], "a 402 keeps an actionable safe message, not the raw upstream body"

    class ProviderStatusError(Exception):
        status = 402

        def __init__(self, message, request_id):
            super().__init__(message)
            self.message = message
            self.request_id = request_id
            self.body = {"error": {"message": message, "request_id": request_id}}

    forwarded = public_error(ProviderStatusError("Insufficient Balance", "SENTINEL-REQ-ID"))
    assert forwarded["code"] == "provider_balance", forwarded
    assert forwarded["message"] == "Insufficient Balance", "the provider's own message is forwarded, not a canned guess"
    assert "SENTINEL-REQ-ID" not in forwarded["message"], "the raw request id never reaches the public message"

    limited = public_error(UpstreamError(sentinel), code="rate_limited")
    assert limited["code"] == "rate_limited", "an explicit code overrides classification"

    # A dict already in public shape passes through; a safe string keeps its message.
    passed = public_error({"code": "auth", "message": "sign in", "retryable": False})
    assert passed == {"code": "auth", "message": "sign in", "retryable": False}
    raw = public_error("SENTINEL-RAW-PROVIDER")
    assert raw["code"] == "provider_error", raw
    assert "SENTINEL-RAW-PROVIDER" not in raw["message"], "an untrusted provider string is never echoed"

    frame = error_frame(UpstreamError(sentinel))
    assert isinstance(frame["error"], str), "the SSE error field stays a string"
    assert frame["code"] == value["code"] and frame["retryable"] == value["retryable"]
    assert sentinel not in frame["error"]
    print("public_error selfcheck ok")


main()
