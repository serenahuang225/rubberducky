"""OpenAI-compatible chat-completions adapter (``POST {base_url}/chat/completions``).

This speaks the plain HTTP protocol over ``httpx`` (a pinned dependency) so it works with any
compatible server (vLLM, llama.cpp, Ollama, hosted gateways) without an extra SDK. The key, if
any, is sent only to the configured base URL: redirects are never followed, plain ``http`` is
accepted only for loopback hosts, and the key never appears in events or errors.

Streaming is used when enabled and requested as server-sent events. The SSE reader keeps its
own byte buffer, so an event split across network chunks (even inside a multibyte character)
is reassembled. A stream that ends without ``[DONE]`` or a ``finish_reason`` is a dropped
connection and is retried, not treated as a complete answer.
"""

import codecs
import json
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import httpx

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
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _validated_base_url(raw: str) -> tuple[str, bool]:
    """(normalized base URL, is_loopback). Credentials need TLS unless the host is loopback."""
    parts = urlsplit(raw.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or not host or parts.username or parts.password:
        raise ProviderConfigError("endpoint", "TUTOR_ENDPOINT_BASE_URL must be an http(s) URL")
    loopback = host in _LOOPBACK_HOSTS
    if parts.scheme == "http" and not loopback:
        raise ProviderConfigError("endpoint", "a non-loopback endpoint must use https")
    return raw.strip().rstrip("/"), loopback


class EndpointAdapter(RemoteAdapter):
    name = "endpoint"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        limits: RemoteLimits,
        streaming: bool = True,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(limits)
        self.base_url, self._loopback = _validated_base_url(base_url)
        self.model = model
        self.streaming = streaming
        self._api_key = api_key
        self._client = http_client or httpx.Client(follow_redirects=False)

    @classmethod
    def from_settings(
        cls, settings: Settings, *, http_client: httpx.Client | None = None
    ) -> "EndpointAdapter":
        if not settings.tutor_endpoint_base_url:
            raise ProviderConfigError("endpoint", "TUTOR_ENDPOINT_BASE_URL is not set")
        if not settings.tutor_endpoint_model:
            raise ProviderConfigError("endpoint", "TUTOR_ENDPOINT_MODEL is not set")
        key = settings.tutor_endpoint_api_key
        return cls(
            base_url=settings.tutor_endpoint_base_url,
            model=settings.tutor_endpoint_model,
            api_key=key.get_secret_value() if key and key.get_secret_value() else None,
            limits=RemoteLimits.from_settings(settings),
            streaming=settings.tutor_endpoint_streaming,
            http_client=http_client,
        )

    def label(self) -> ProviderLabel:
        where = "on this machine" if self._loopback else "sends context to a remote server"
        return ProviderLabel(
            name=self.name,
            is_mock=False,
            label=f"OpenAI-compatible {self.model[:50]} ({where})"[:120],
        )

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            streaming=self.streaming,
            cancellable=True,
            retries=True,
            transmission="loopback" if self._loopback else "remote_provider",
        )

    # -- transport -----------------------------------------------------------------------

    def _complete(self, call: CallContext) -> Completion:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in call.messages],
            "max_tokens": call.max_output_tokens,
            "temperature": 0,
            "stream": self.streaming,
        }
        if self.streaming:
            body["stream_options"] = {"include_usage": True}
        headers = {"content-type": "application/json", "accept": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        timeout = max(0.001, call.deadline.remaining())
        try:
            request = self._client.build_request(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=headers,
                content=json.dumps(body),
                timeout=timeout,
            )
            response = self._client.send(request, stream=True, follow_redirects=False)
        except Exception as error:
            raise _translate(error, call.cancel) from None
        unregister = call.cancel.on_cancel(response.close)
        try:
            _check_status(response)
            if self.streaming:
                return self._read_stream(response, call)
            return self._read_json(response)
        except ProviderError:
            raise
        except Exception as error:
            raise _translate(error, call.cancel) from None
        finally:
            unregister()
            response.close()

    def _read_json(self, response: httpx.Response) -> Completion:
        raw = response.read()
        if len(raw) > 4 * MAX_RAW_OUTPUT_CHARS:
            raise MalformedDraftError("provider output exceeded the accepted size")
        try:
            payload = json.loads(raw)
            choice = payload["choices"][0]
            text = choice["message"]["content"]
            finish = choice.get("finish_reason")
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderProtocolError("endpoint response had no completion text") from None
        if not isinstance(text, str):
            raise ProviderProtocolError("endpoint completion text was not a string")
        usage = payload.get("usage") if isinstance(payload, dict) else None
        return Completion(
            text=text,
            input_tokens=_usage(usage, "prompt_tokens"),
            output_tokens=_usage(usage, "completion_tokens"),
            hit_length_limit=finish == "length",
        )

    def _read_stream(self, response: httpx.Response, call: CallContext) -> Completion:
        pieces: list[str] = []
        size = 0
        finish: str | None = None
        usage: Any = None
        done = False
        for data in _sse_data(response.iter_bytes()):
            call.cancel.raise_if_cancelled()
            call.deadline.raise_if_expired()
            if data == "[DONE]":
                done = True
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                raise ProviderProtocolError("endpoint sent a malformed stream event") from None
            if not isinstance(chunk, dict):
                raise ProviderProtocolError("endpoint sent an unexpected stream event")
            if "error" in chunk:
                raise TransientProviderError("endpoint reported an error mid-stream")
            if chunk.get("usage"):
                usage = chunk["usage"]
            for choice in chunk.get("choices") or []:
                delta = (choice.get("delta") or {}).get("content")
                if isinstance(delta, str) and delta:
                    size += len(delta)
                    if size > MAX_RAW_OUTPUT_CHARS:
                        raise MalformedDraftError("provider output exceeded the accepted size")
                    pieces.append(delta)
                    call.recorder.emit("delta", text=delta)
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
        if not done and finish is None:
            raise TransientProviderError("endpoint stream ended before completion")
        return Completion(
            text="".join(pieces),
            input_tokens=_usage(usage, "prompt_tokens"),
            output_tokens=_usage(usage, "completion_tokens"),
            hit_length_limit=finish == "length",
        )


def _usage(usage: Any, key: str) -> int | None:
    value = usage.get(key) if isinstance(usage, dict) else None
    return value if isinstance(value, int) and value >= 0 else None


def _sse_data(chunks: Iterator[bytes]) -> Iterator[str]:
    """Yield each SSE event's ``data`` payload, whatever way the bytes were chunked."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    buffer = ""
    for chunk in chunks:
        try:
            buffer += decoder.decode(chunk)
        except UnicodeDecodeError:
            raise ProviderProtocolError("endpoint stream was not valid UTF-8") from None
        buffer = buffer.replace("\r\n", "\n")
        while "\n\n" in buffer:
            event, buffer = buffer.split("\n\n", 1)
            data = "\n".join(
                line[5:].lstrip(" ") for line in event.split("\n") if line.startswith("data:")
            )
            if data:
                yield data
        if len(buffer) > 4 * MAX_RAW_OUTPUT_CHARS:
            raise ProviderProtocolError("endpoint stream event exceeded the accepted size")
    # A final event without its blank-line terminator is an incomplete event; drop it.


def _check_status(response: httpx.Response) -> None:
    status = response.status_code
    if status < 300:
        return
    if status in (401, 403):
        raise ProviderAuthError(f"endpoint rejected credentials (HTTP {status})")
    if status in _TRANSIENT_STATUSES or status >= 500:
        raise TransientProviderError(
            f"endpoint returned HTTP {status}", retry_after=_retry_after(response)
        )
    raise ProviderRejectedError(f"endpoint rejected the request (HTTP {status})")


def _retry_after(response: httpx.Response) -> float | None:
    try:
        value = float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
    return value if value >= 0 else None


def _translate(error: Exception, cancel: CancelToken) -> ProviderError:
    if cancel.cancelled:
        return ProviderCancelledError(f"endpoint call cancelled ({cancel.reason})")
    if isinstance(error, httpx.TimeoutException):
        return ProviderTimeoutError("endpoint request timed out")
    if isinstance(error, httpx.TransportError):
        return TransientProviderError("endpoint connection failed")
    return ProviderProtocolError(f"endpoint response could not be read ({type(error).__name__})")
