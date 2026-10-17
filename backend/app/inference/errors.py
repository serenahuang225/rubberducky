"""Typed provider failures.

Every adapter failure is a :class:`ProviderError` with a stable ``code`` and a fixed,
learner-safe ``public_message``. Messages never embed credentials, request bodies or SDK
exception text, so they can be stored on a failed turn and logged without redaction.
``recoverable`` says whether a later attempt (a new turn, or a fixed configuration) can
succeed; ``retryable`` says whether the adapter itself may repeat the same call.
"""


class ProviderError(Exception):
    code = "provider_error"
    recoverable = True
    retryable = False
    public_message = "The tutor provider could not produce a draft."

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.public_message)
        self.detail = detail or self.public_message


class ProviderUnavailableError(ProviderError, RuntimeError):
    """The configured provider cannot be used in this build or configuration; never faked."""

    code = "provider_unavailable"
    recoverable = False

    def __init__(self, provider: str, reason: str | None = None) -> None:
        detail = f"tutor provider {provider!r} is not available in this build"
        if reason:
            detail = f"tutor provider {provider!r} is not available: {reason}"
        super().__init__(detail)
        self.provider = provider
        self.reason = reason


class ProviderDisabledError(ProviderUnavailableError):
    code = "provider_disabled"


class ProviderConfigError(ProviderUnavailableError):
    code = "provider_misconfigured"


class DeviceUnavailableError(ProviderError):
    code = "device_unavailable"
    recoverable = False
    public_message = "The configured local device is not available on this machine."


class ModelLoadError(ProviderError):
    code = "model_load_failed"
    public_message = "The local model could not be loaded."


class ProviderBusyError(ProviderError):
    code = "provider_busy"
    public_message = "The tutor model is busy; try again shortly."


class RequestTooLargeError(ProviderError):
    code = "request_too_large"
    recoverable = False
    public_message = "The request does not fit this provider's configured limits."


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"
    public_message = "The provider did not answer within the deadline."


class ProviderCancelledError(ProviderError):
    code = "provider_cancelled"
    public_message = "The provider call was cancelled."


class TransientProviderError(ProviderError):
    """A failure worth repeating (network, rate limit, overload)."""

    code = "provider_transient"
    retryable = True
    public_message = "The provider is temporarily unavailable."

    def __init__(self, detail: str | None = None, *, retry_after: float | None = None) -> None:
        super().__init__(detail)
        self.retry_after = retry_after


class RetriesExhaustedError(ProviderError):
    code = "provider_retries_exhausted"
    public_message = "The provider stayed unavailable after the allowed attempts."

    def __init__(self, attempts: int, last: ProviderError) -> None:
        super().__init__(f"{last.public_message} (after {attempts} attempts)")
        self.attempts = attempts
        self.last = last


class ProviderAuthError(ProviderError):
    code = "provider_auth_failed"
    recoverable = False
    public_message = "The provider rejected the configured credentials."


class ProviderRejectedError(ProviderError):
    code = "provider_rejected_request"
    recoverable = False
    public_message = "The provider rejected the request."


class ProviderProtocolError(ProviderError):
    """A response or stream the transport could not interpret."""

    code = "provider_protocol_error"
    public_message = "The provider sent a response this adapter could not read."


class MalformedDraftError(ProviderError):
    """The completed output is not a complete, current, valid draft; nothing is committed."""

    code = "malformed_draft"
    public_message = "The provider's answer was not a valid tutor draft."


class StaleDraftError(MalformedDraftError):
    code = "stale_draft"
    public_message = "The provider's draft was for a different turn or session revision."


class TruncatedDraftError(MalformedDraftError):
    code = "draft_truncated"
    public_message = "The provider's answer was cut off by the output limit."
