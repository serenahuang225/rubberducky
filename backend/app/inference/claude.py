"""Claude adapter on the official Anthropic SDK (streaming Messages API).

Nothing is contacted when this module is imported or when the adapter is constructed. The SDK
client is built with ``max_retries=0`` because retry policy, deadline and cancellation belong
to :class:`RemoteAdapter`. The API key lives only in the SDK client's auth header; it is never
placed in events, error messages or logs. Without ``ANTHROPIC_MODEL`` the adapter refuses to
build: no default model is guessed, since available models change over time.
"""

from typing import Any

import anthropic
import httpx2

from app.config import Settings
from app.inference.cancel import CancelToken
from app.inference.errors import (
    MalformedDraftError,
    ProviderAuthError,
    ProviderCancelledError,
    ProviderConfigError,
    ProviderError,
    ProviderProtocolError,
    ProviderRejectedError,
    ProviderTimeoutError,
    TransientProviderError,
)
from app.inference.events import MAX_RAW_OUTPUT_CHARS, AdapterCapabilities
from app.inference.remote import CallContext, Completion, RemoteAdapter, RemoteLimits
from app.schemas.tutor import ProviderLabel

_TRANSIENT_STATUSES = {408, 409, 425, 429}


class ClaudeAdapter(RemoteAdapter):
    name = "claude"

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        limits: RemoteLimits,
        http_client: httpx2.Client | None = None,
    ) -> None:
        super().__init__(limits)
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=0, http_client=http_client)

    @classmethod
    def from_settings(
        cls, settings: Settings, *, http_client: httpx2.Client | None = None
    ) -> "ClaudeAdapter":
        if settings.anthropic_api_key is None or not settings.anthropic_api_key.get_secret_value():
            raise ProviderConfigError("claude", "ANTHROPIC_API_KEY is not set")
        if not settings.anthropic_model:
            raise ProviderConfigError("claude", "ANTHROPIC_MODEL is not set")
        return cls(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key.get_secret_value(),
            limits=RemoteLimits.from_settings(settings),
            http_client=http_client,
        )

    def label(self) -> ProviderLabel:
        return ProviderLabel(
            name=self.name,
            is_mock=False,
            label=f"Claude {self.model[:60]} (sends context to Anthropic)"[:120],
        )

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            streaming=True, cancellable=True, retries=True, transmission="remote_provider"
        )

    def _complete(self, call: CallContext) -> Completion:
        system = "\n\n".join(m.content for m in call.messages if m.role == "system")
        turns = [
            {"role": m.role, "content": m.content} for m in call.messages if m.role != "system"
        ]
        pieces: list[str] = []
        size = 0
        try:
            with self._client.messages.stream(
                model=self.model,
                max_tokens=call.max_output_tokens,
                system=system,
                messages=turns,  # type: ignore[arg-type]
                timeout=max(0.001, call.deadline.remaining()),
            ) as stream:
                unregister = call.cancel.on_cancel(stream.close)
                try:
                    for fragment in stream.text_stream:
                        call.cancel.raise_if_cancelled()
                        call.deadline.raise_if_expired()
                        size += len(fragment)
                        if size > MAX_RAW_OUTPUT_CHARS:
                            raise MalformedDraftError("provider output exceeded the accepted size")
                        pieces.append(fragment)
                        call.recorder.emit("delta", text=fragment)
                    final = stream.get_final_message()
                finally:
                    unregister()
            # The SDK returns whatever it accumulated when the connection drops mid-stream;
            # only a message_delta carrying a stop_reason proves the message finished.
            if final.stop_reason is None:
                raise TransientProviderError("claude stream ended before the message completed")
        except ProviderError:
            raise
        except Exception as error:
            raise _translate(error, call.cancel) from None
        return Completion(
            text="".join(pieces),
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
            hit_length_limit=final.stop_reason == "max_tokens",
        )


def _retry_after(response: Any) -> float | None:
    raw = response.headers.get("retry-after") if response is not None else None
    try:
        value = float(raw) if raw is not None else None
    except ValueError:
        return None
    return value if value is not None and value >= 0 else None


def _translate(error: Exception, cancel: CancelToken) -> ProviderError:
    """Map an SDK/transport failure to a typed error that carries no SDK text or secrets."""
    if cancel.cancelled:
        return ProviderCancelledError(f"claude call cancelled ({cancel.reason})")
    if isinstance(error, anthropic.APITimeoutError):
        return ProviderTimeoutError("claude request timed out")
    if isinstance(error, anthropic.APIConnectionError):
        return TransientProviderError("claude connection failed")
    if isinstance(error, anthropic.APIStatusError):
        status = error.status_code
        if status in (401, 403):
            return ProviderAuthError(f"claude rejected credentials (HTTP {status})")
        if status in _TRANSIENT_STATUSES or status >= 500:
            return TransientProviderError(
                f"claude returned HTTP {status}", retry_after=_retry_after(error.response)
            )
        return ProviderRejectedError(f"claude rejected the request (HTTP {status})")
    if isinstance(error, RuntimeError):
        # The SDK raises this when the SSE stream ends before the message completes.
        return TransientProviderError("claude stream ended before the message completed")
    return ProviderProtocolError(f"claude response could not be read ({type(error).__name__})")
