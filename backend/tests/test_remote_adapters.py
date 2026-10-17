"""Endpoint and Claude adapters through their real HTTP stacks, with transport fixtures.

The OpenAI-compatible adapter runs on ``httpx``; the Claude adapter runs the official
``anthropic`` SDK, which uses ``httpx2`` (not ``httpx``) in the installed version. Both get
an in-process ``MockTransport`` so the actual request building, status handling, SSE parsing
and stream decoding execute, while outbound sockets stay blocked. These are transport
*fixtures*: they establish call shapes and failure normalisation, not live provider quality.
"""

import json
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import httpx2
import pytest

from app.db.database import Database
from app.inference.cancel import CancelToken
from app.inference.claude import ClaudeAdapter
from app.inference.endpoint import EndpointAdapter
from app.inference.errors import (
    MalformedDraftError,
    ProviderAuthError,
    ProviderBusyError,
    ProviderCancelledError,
    ProviderConfigError,
    ProviderProtocolError,
    ProviderRejectedError,
    ProviderTimeoutError,
    RequestTooLargeError,
    RetriesExhaustedError,
    StaleDraftError,
    TruncatedDraftError,
)
from app.inference.providers import DraftInputs
from app.inference.remote import MAX_CONCURRENT_CALLS, RemoteAdapter
from app.inference.request import ProviderBudget
from tests.provider_fixtures import (
    SECRET,
    TURN_ID,
    chunked,
    fast_limits,
    make_inputs,
    reply_for_request,
    settings_for,
    valid_draft_json,
)

MODEL = "fixture-model-1"


@pytest.fixture(autouse=True)
def _blocked(no_network: list) -> list:
    return no_network


@pytest.fixture
def inputs(database: Database) -> DraftInputs:
    return make_inputs(database)


def with_cancel(inputs: DraftInputs, token: CancelToken) -> DraftInputs:
    return DraftInputs(**{**inputs.__dict__, "cancel": token})


# ---------------------------------------------------------------------------------------
# A scripted server. One "script step" answers one HTTP request; the request is recorded.
# ---------------------------------------------------------------------------------------


@dataclass
class Wire:
    lib: Any
    steps: list[Callable[[Any], Any]]
    requests: list[Any]

    def handler(self, request: Any) -> Any:
        self.requests.append(request)
        index = min(len(self.requests), len(self.steps)) - 1
        return self.steps[index](request)

    def transport(self) -> Any:
        return self.lib.MockTransport(self.handler)

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]


def wire(lib: Any, *steps: Callable[[Any], Any]) -> Wire:
    return Wire(lib, list(steps), [])


def status(lib: Any, code: int, headers: dict[str, str] | None = None) -> Callable[[Any], Any]:
    return lambda _r: lib.Response(code, headers=headers or {}, json={"error": "scripted"})


def raising(error: Exception) -> Callable[[Any], Any]:
    def step(_r: Any) -> Any:
        raise error

    return step


# ----------------------------- OpenAI-compatible endpoint ------------------------------


def endpoint_adapter(
    w: Wire,
    *,
    streaming: bool = True,
    base_url: str = "https://llm.example.test/v1",
    api_key: str | None = SECRET,
    **limits: Any,
) -> EndpointAdapter:
    return EndpointAdapter(
        base_url=base_url,
        model=MODEL,
        api_key=api_key,
        limits=fast_limits(**limits),
        streaming=streaming,
        http_client=httpx.Client(transport=w.transport(), follow_redirects=False),
    )


def sse_event(payload: dict[str, Any] | str) -> bytes:
    data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return f"data: {data}\n\n".encode()


def chat_stream(text: str, *, finish: str | None = "stop", done: bool = True) -> bytes:
    third = max(1, len(text) // 3)
    parts = [text[i : i + third] for i in range(0, len(text), third)]
    body = b"".join(sse_event({"choices": [{"delta": {"content": part}}]}) for part in parts)
    if finish:
        body += sse_event({"choices": [{"delta": {}, "finish_reason": finish}]})
    body += sse_event({"choices": [], "usage": {"prompt_tokens": 321, "completion_tokens": 45}})
    if done:
        body += sse_event("[DONE]")
    return body


def stream_reply(body: bytes, *, chunk: int | None = None) -> Callable[[Any], Any]:
    pieces: Any = chunked(body, chunk) if chunk else [body]
    return lambda _r: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, content=iter(pieces)
    )


def json_reply(text: str, finish: str = "stop") -> Callable[[Any], Any]:
    return lambda _r: httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"role": "assistant", "content": text}, "finish_reason": finish}
            ],
            "usage": {"prompt_tokens": 111, "completion_tokens": 22},
        },
    )


class TestEndpointValidAndRequestShape:
    def test_streamed_completion_becomes_a_validated_draft_with_usage(
        self, inputs: DraftInputs
    ) -> None:
        w = wire(httpx, stream_reply(chat_stream(valid_draft_json(inputs))))
        outcome = endpoint_adapter(w).draft_outcome(inputs)
        assert outcome.draft.turn_id == TURN_ID
        assert outcome.attempts == 1
        assert (outcome.input_tokens, outcome.output_tokens) == (321, 45)
        kinds = [e.kind for e in outcome.events]
        assert kinds[0] == "started" and kinds[-1] == "completed"
        assert kinds.count("delta") >= 3

    def test_non_streaming_json_completion(self, inputs: DraftInputs) -> None:
        w = wire(httpx, json_reply(valid_draft_json(inputs)))
        adapter = endpoint_adapter(w, streaming=False)
        outcome = adapter.draft_outcome(inputs)
        assert outcome.draft.turn_id == TURN_ID
        assert (outcome.input_tokens, outcome.output_tokens) == (111, 22)
        assert [e.kind for e in outcome.events] == ["started", "completed"]
        assert adapter.capabilities().streaming is False
        assert w.bodies()[0]["stream"] is False
        assert "stream_options" not in w.bodies()[0]

    def test_request_shape_target_headers_and_bounds(self, inputs: DraftInputs) -> None:
        w = wire(httpx, stream_reply(chat_stream(valid_draft_json(inputs))))
        endpoint_adapter(w, max_output_tokens=77).draft_outcome(inputs)
        (request,) = w.requests
        assert request.method == "POST"
        assert str(request.url) == "https://llm.example.test/v1/chat/completions"
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        body = w.bodies()[0]
        assert body["model"] == MODEL
        assert body["max_tokens"] == 77
        assert body["temperature"] == 0
        assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
        roles = [m["role"] for m in body["messages"]]
        assert roles == ["system", "user"]
        assert "Respond with ONE JSON object" in body["messages"][0]["content"]
        assert inputs.plan.turn_id in body["messages"][0]["content"]

    def test_output_ceiling_never_exceeds_the_request_budget(self, inputs: DraftInputs) -> None:
        w = wire(httpx, stream_reply(chat_stream(valid_draft_json(inputs))))
        endpoint_adapter(w, max_output_tokens=4_000).draft_outcome(inputs)
        assert w.bodies()[0]["max_tokens"] == inputs.request.max_output_tokens

    def test_keyless_loopback_server_sends_no_authorization_and_says_it_is_local(
        self, inputs: DraftInputs
    ) -> None:
        w = wire(httpx, stream_reply(chat_stream(valid_draft_json(inputs))))
        adapter = endpoint_adapter(w, base_url="http://127.0.0.1:8000/v1/", api_key=None)
        adapter.draft_outcome(inputs)
        assert "authorization" not in w.requests[0].headers
        assert str(w.requests[0].url) == "http://127.0.0.1:8000/v1/chat/completions"
        assert adapter.capabilities().transmission == "loopback"
        assert "on this machine" in adapter.label().label


class TestEndpointSecretsAndDisclosure:
    def test_secret_never_appears_in_events_labels_or_errors(self, inputs: DraftInputs) -> None:
        w = wire(httpx, status(httpx, 503))
        adapter = endpoint_adapter(w)
        with pytest.raises(RetriesExhaustedError) as caught:
            adapter.draft_outcome(inputs)
        everything = repr((str(caught.value), adapter.label(), vars(caught.value)))
        assert SECRET not in everything
        ok = endpoint_adapter(wire(httpx, stream_reply(chat_stream(valid_draft_json(inputs)))))
        outcome = ok.draft_outcome(inputs)
        assert SECRET not in repr(outcome.events) + repr(ok.label())

    def test_remote_endpoint_discloses_transmission_and_never_uses_plain_http(self) -> None:
        w = wire(httpx, status(httpx, 500))
        adapter = endpoint_adapter(w)
        assert adapter.capabilities().transmission == "remote_provider"
        assert "sends context to a remote server" in adapter.label().label
        assert adapter.label().is_mock is False
        with pytest.raises(ProviderConfigError, match="https"):
            endpoint_adapter(w, base_url="http://llm.example.test/v1")

    @pytest.mark.parametrize(
        "url", ["ftp://llm.example.test", "https://user:pw@llm.example.test/v1", "not a url"]
    )
    def test_unusable_base_urls_are_refused(self, url: str) -> None:
        with pytest.raises(ProviderConfigError):
            endpoint_adapter(wire(httpx, status(httpx, 500)), base_url=url)

    def test_redirects_are_not_followed_so_the_key_stays_on_the_configured_host(
        self, inputs: DraftInputs
    ) -> None:
        w = wire(
            httpx,
            lambda _r: httpx.Response(307, headers={"location": "https://evil.example.test/steal"}),
        )
        with pytest.raises(ProviderRejectedError):
            endpoint_adapter(w).draft_outcome(inputs)
        assert len(w.requests) == 1
        assert str(w.requests[0].url).startswith("https://llm.example.test/")

    def test_from_settings_needs_url_and_model_and_reads_the_secret_server_side(self) -> None:
        with pytest.raises(ProviderConfigError, match="BASE_URL"):
            EndpointAdapter.from_settings(settings_for(tutor_endpoint_model=MODEL))
        with pytest.raises(ProviderConfigError, match="MODEL"):
            EndpointAdapter.from_settings(
                settings_for(tutor_endpoint_base_url="https://llm.example.test/v1")
            )
        adapter = EndpointAdapter.from_settings(
            settings_for(
                tutor_endpoint_base_url="https://llm.example.test/v1",
                tutor_endpoint_model=MODEL,
                tutor_endpoint_api_key=SECRET,
            )
        )
        assert adapter._api_key == SECRET
        assert SECRET not in repr(settings_for(tutor_endpoint_api_key=SECRET)), (
            "settings must not repr a secret"
        )


class TestEndpointStreams:
    @pytest.mark.parametrize("size", [1, 2, 3, 7, 64])
    def test_events_split_across_network_chunks_are_reassembled(
        self, inputs: DraftInputs, size: int
    ) -> None:
        # The utterance has multibyte characters, so small chunks split inside a character.
        draft_json = valid_draft_json(inputs, utterance="Try √(2x) ≥ 3 and group the terms.")
        w = wire(httpx, stream_reply(chat_stream(draft_json), chunk=size))
        outcome = endpoint_adapter(w).draft_outcome(inputs)
        assert outcome.draft.utterance == "Try √(2x) ≥ 3 and group the terms."
        assert "".join(e.text for e in outcome.events if e.kind == "delta") == draft_json

    def test_crlf_framing_and_comment_lines_are_accepted(self, inputs: DraftInputs) -> None:
        body = chat_stream(valid_draft_json(inputs)).replace(b"\n", b"\r\n")
        body = b": keep-alive\r\n\r\n" + body
        outcome = endpoint_adapter(wire(httpx, stream_reply(body, chunk=5))).draft_outcome(inputs)
        assert outcome.draft.turn_id == TURN_ID

    def test_a_malformed_stream_event_is_a_protocol_error_and_not_retried(
        self, inputs: DraftInputs
    ) -> None:
        w = wire(httpx, stream_reply(b"data: {not json}\n\n"))
        with pytest.raises(ProviderProtocolError):
            endpoint_adapter(w).draft_outcome(inputs)
        assert len(w.requests) == 1

    def test_invalid_utf8_in_the_stream_is_a_protocol_error(self, inputs: DraftInputs) -> None:
        w = wire(httpx, stream_reply(b"data: \xff\xfe\n\n"))
        with pytest.raises(ProviderProtocolError):
            endpoint_adapter(w).draft_outcome(inputs)

    def test_a_stream_cut_before_completion_is_retried_and_never_committed_partial(
        self, inputs: DraftInputs
    ) -> None:
        full = valid_draft_json(inputs)
        cut = chat_stream(full[: len(full) // 2], finish=None, done=False)
        w = wire(httpx, stream_reply(cut), stream_reply(chat_stream(full)))
        outcome = endpoint_adapter(w).draft_outcome(inputs)
        assert len(w.requests) == 2 and outcome.attempts == 2
        assert [e.kind for e in outcome.events if e.kind in ("retry", "completed")] == [
            "retry",
            "completed",
        ]

    def test_a_half_event_without_its_terminator_is_dropped_not_completed(
        self, inputs: DraftInputs
    ) -> None:
        body = chat_stream(valid_draft_json(inputs), finish=None, done=False)
        body += b'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}'
        w = wire(httpx, stream_reply(body))
        with pytest.raises(RetriesExhaustedError):
            endpoint_adapter(w, max_attempts=2).draft_outcome(inputs)

    def test_an_error_event_inside_the_stream_is_transient(self, inputs: DraftInputs) -> None:
        w = wire(
            httpx,
            stream_reply(sse_event({"error": {"message": "overloaded"}})),
            stream_reply(chat_stream(valid_draft_json(inputs))),
        )
        assert endpoint_adapter(w).draft_outcome(inputs).attempts == 2

    def test_output_over_the_size_ceiling_is_rejected_while_streaming(
        self, inputs: DraftInputs
    ) -> None:
        w = wire(httpx, stream_reply(chat_stream("x" * 30_000)))
        with pytest.raises(MalformedDraftError, match="size"):
            endpoint_adapter(w).draft_outcome(inputs)
        assert len(w.requests) == 1


class TestEndpointFinalDraftValidation:
    def test_valid_json_for_the_wrong_turn_is_stale_and_not_retried(
        self, inputs: DraftInputs
    ) -> None:
        w = wire(httpx, stream_reply(chat_stream(valid_draft_json(inputs, turn_id="old-turn"))))
        with pytest.raises(StaleDraftError):
            endpoint_adapter(w).draft_outcome(inputs)
        assert len(w.requests) == 1

    def test_valid_json_for_an_older_revision_is_stale(self, inputs: DraftInputs) -> None:
        w = wire(httpx, stream_reply(chat_stream(valid_draft_json(inputs, session_revision=0))))
        with pytest.raises(StaleDraftError):
            endpoint_adapter(w).draft_outcome(inputs)

    @pytest.mark.parametrize(
        "text",
        [
            "Sure! Here is a hint.",
            '{"schema_version": "tutor-draft.v1", "turn_id": "x"}',
            '{"utterance": "hi"} trailing prose',
            "[]",
        ],
    )
    def test_malformed_final_drafts_are_typed_rejections_without_a_second_call(
        self, inputs: DraftInputs, text: str
    ) -> None:
        w = wire(httpx, stream_reply(chat_stream(text)))
        with pytest.raises(MalformedDraftError):
            endpoint_adapter(w).draft_outcome(inputs)
        assert len(w.requests) == 1

    def test_json_wrapped_in_a_code_fence_is_accepted_but_nothing_else_is_repaired(
        self, inputs: DraftInputs
    ) -> None:
        fenced = f"```json\n{valid_draft_json(inputs)}\n```"
        w = wire(httpx, stream_reply(chat_stream(fenced)))
        assert endpoint_adapter(w).draft_outcome(inputs).draft.turn_id == TURN_ID

    def test_length_finish_means_truncated_and_never_commits(self, inputs: DraftInputs) -> None:
        w = wire(httpx, stream_reply(chat_stream(valid_draft_json(inputs), finish="length")))
        with pytest.raises(TruncatedDraftError):
            endpoint_adapter(w).draft_outcome(inputs)
        w2 = wire(httpx, json_reply(valid_draft_json(inputs), finish="length"))
        with pytest.raises(TruncatedDraftError):
            endpoint_adapter(w2, streaming=False).draft_outcome(inputs)

    @pytest.mark.parametrize(
        "payload", [{"choices": []}, {"choices": [{"message": {"content": 5}}]}, {"x": 1}]
    )
    def test_unreadable_json_completions_are_protocol_errors(
        self, inputs: DraftInputs, payload: dict[str, Any]
    ) -> None:
        w = wire(httpx, lambda _r: httpx.Response(200, json=payload))
        with pytest.raises(ProviderProtocolError):
            endpoint_adapter(w, streaming=False).draft_outcome(inputs)


class TestEndpointRetryTimeoutCancel:
    @pytest.mark.parametrize("code", [429, 500, 502, 503, 529])
    def test_transient_statuses_retry_then_succeed(self, inputs: DraftInputs, code: int) -> None:
        w = wire(
            httpx,
            status(httpx, code),
            stream_reply(chat_stream(valid_draft_json(inputs))),
        )
        outcome = endpoint_adapter(w).draft_outcome(inputs)
        assert outcome.attempts == 2 and len(w.requests) == 2
        assert [e.code for e in outcome.events if e.kind == "retry"] == ["provider_transient"]

    def test_exhaustion_stops_at_the_configured_attempts_with_a_typed_error(
        self, inputs: DraftInputs
    ) -> None:
        w = wire(httpx, status(httpx, 503))
        adapter = endpoint_adapter(w, max_attempts=3)
        with pytest.raises(RetriesExhaustedError) as caught:
            adapter.draft_outcome(inputs)
        assert caught.value.attempts == 3
        assert len(w.requests) == 3 == adapter.calls_made
        assert caught.value.code == "provider_retries_exhausted"

    def test_a_single_attempt_configuration_never_retries(self, inputs: DraftInputs) -> None:
        w = wire(httpx, status(httpx, 503))
        with pytest.raises(RetriesExhaustedError):
            endpoint_adapter(w, max_attempts=1).draft_outcome(inputs)
        assert len(w.requests) == 1

    @pytest.mark.parametrize("code", [401, 403])
    def test_rejected_credentials_are_not_retried(self, inputs: DraftInputs, code: int) -> None:
        w = wire(httpx, status(httpx, code))
        with pytest.raises(ProviderAuthError) as caught:
            endpoint_adapter(w).draft_outcome(inputs)
        assert len(w.requests) == 1
        assert caught.value.recoverable is False

    def test_client_errors_are_rejections_not_retries(self, inputs: DraftInputs) -> None:
        w = wire(httpx, status(httpx, 400))
        with pytest.raises(ProviderRejectedError):
            endpoint_adapter(w).draft_outcome(inputs)
        assert len(w.requests) == 1

    def test_connection_failures_are_transient_and_exhaust(self, inputs: DraftInputs) -> None:
        w = wire(httpx, raising(httpx.ConnectError("boom with secret " + SECRET)))
        with pytest.raises(RetriesExhaustedError) as caught:
            endpoint_adapter(w).draft_outcome(inputs)
        assert SECRET not in str(caught.value) + repr(vars(caught.value))
        assert len(w.requests) == 3

    def test_transport_timeout_is_a_timeout_error_and_not_a_blind_retry(
        self, inputs: DraftInputs
    ) -> None:
        w = wire(httpx, raising(httpx.ReadTimeout("slow")))
        with pytest.raises(ProviderTimeoutError):
            endpoint_adapter(w).draft_outcome(inputs)
        assert len(w.requests) == 1

    def test_the_http_client_receives_the_remaining_deadline_as_its_timeout(
        self, inputs: DraftInputs
    ) -> None:
        w = wire(httpx, stream_reply(chat_stream(valid_draft_json(inputs))))
        endpoint_adapter(w, timeout_seconds=4.0).draft_outcome(inputs)
        timeout = w.requests[0].extensions["timeout"]
        assert 0 < timeout["read"] <= 4.0

    def test_default_client_against_blocked_network_fails_transient_and_exhausts(
        self, inputs: DraftInputs, no_network: list
    ) -> None:
        adapter = EndpointAdapter(
            base_url="https://llm.example.test/v1",
            model=MODEL,
            api_key=SECRET,
            limits=fast_limits(max_attempts=2),
        )
        with pytest.raises(RetriesExhaustedError):
            adapter.draft_outcome(inputs)
        assert adapter.calls_made == 2
        assert no_network, "the real HTTP client really tried to connect, and was refused"

    def test_deadline_between_chunks_stops_reading_and_commits_nothing(
        self, inputs: DraftInputs
    ) -> None:
        def slow_stream(_r: Any) -> Any:
            def chunks() -> Iterator[bytes]:
                yield sse_event({"choices": [{"delta": {"content": '{"a":'}}]})
                time.sleep(0.4)
                yield sse_event({"choices": [{"delta": {"content": "1}"}}]})
                yield sse_event("[DONE]")

            return httpx.Response(200, content=chunks())

        adapter = endpoint_adapter(wire(httpx, slow_stream), timeout_seconds=0.2)
        with pytest.raises(ProviderTimeoutError):
            adapter.draft_outcome(inputs)

    def test_backoff_never_sleeps_past_the_deadline(self, inputs: DraftInputs) -> None:
        w = wire(httpx, status(httpx, 429, {"retry-after": "30"}))
        adapter = endpoint_adapter(w, timeout_seconds=1.0, backoff_seconds=0.0)
        started = time.monotonic()
        with pytest.raises(ProviderTimeoutError):
            adapter.draft_outcome(inputs)
        assert time.monotonic() - started < 0.9
        assert len(w.requests) == 1

    def test_retry_after_is_honored_within_the_deadline(self, inputs: DraftInputs) -> None:
        w = wire(
            httpx,
            status(httpx, 429, {"retry-after": "0.2"}),
            stream_reply(chat_stream(valid_draft_json(inputs))),
        )
        started = time.monotonic()
        outcome = endpoint_adapter(w).draft_outcome(inputs)
        assert time.monotonic() - started >= 0.19
        assert outcome.attempts == 2

    def test_cancel_before_the_call_sends_nothing(self, inputs: DraftInputs) -> None:
        w = wire(httpx, stream_reply(chat_stream(valid_draft_json(inputs))))
        token = CancelToken()
        token.cancel("gone")
        with pytest.raises(ProviderCancelledError):
            endpoint_adapter(w).draft_outcome(with_cancel(inputs, token))
        assert w.requests == []

    def test_cancel_during_backoff_wakes_the_caller_at_once(self, inputs: DraftInputs) -> None:
        w = wire(httpx, status(httpx, 503), status(httpx, 503))
        adapter = endpoint_adapter(w, backoff_seconds=5.0, timeout_seconds=30.0)
        token = CancelToken()
        threading.Timer(0.1, token.cancel).start()
        started = time.monotonic()
        with pytest.raises(ProviderCancelledError):
            adapter.draft_outcome(with_cancel(inputs, token))
        assert time.monotonic() - started < 2.0
        assert len(w.requests) == 1

    def test_cancel_releases_a_blocked_stream_read_and_nothing_commits(
        self, inputs: DraftInputs
    ) -> None:
        release = threading.Event()
        closed = threading.Event()

        class Hanging(httpx.SyncByteStream):
            def __iter__(self) -> Iterator[bytes]:
                yield sse_event({"choices": [{"delta": {"content": '{"turn'}}]})
                release.wait(timeout=10)

            def close(self) -> None:
                closed.set()
                release.set()

        w = wire(httpx, lambda _r: httpx.Response(200, stream=Hanging()))
        adapter = endpoint_adapter(w, timeout_seconds=30.0)
        token = CancelToken()
        seen: list[str] = []
        watched = DraftInputs(
            **{**inputs.__dict__, "cancel": token, "on_event": lambda e: seen.append(e.kind)}
        )
        result: list[BaseException] = []

        def call() -> None:
            try:
                adapter.draft_outcome(watched)
            except BaseException as error:
                result.append(error)

        thread = threading.Thread(target=call)
        thread.start()
        deadline = time.monotonic() + 5
        while "delta" not in seen and time.monotonic() < deadline:
            time.sleep(0.01)
        token.cancel("user left")
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert closed.is_set(), "cancel must close the in-flight response"
        assert [type(e) for e in result] == [ProviderCancelledError]
        assert "completed" not in seen

    def test_late_completion_after_cancel_is_fenced(self, inputs: DraftInputs) -> None:
        token = CancelToken()

        def cancel_then_answer(_r: Any) -> Any:
            token.cancel("cancelled while the provider was answering")
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": valid_draft_json(inputs)},
                            "finish_reason": "stop",
                        }
                    ]
                },
            )

        adapter = endpoint_adapter(wire(httpx, cancel_then_answer), streaming=False)
        with pytest.raises(ProviderCancelledError):
            adapter.draft_outcome(with_cancel(inputs, token))


# ----------------------------------- Claude ---------------------------------------------


def claude_adapter(w: Wire, **limits: Any) -> ClaudeAdapter:
    return ClaudeAdapter(
        model=MODEL,
        api_key=SECRET,
        limits=fast_limits(**limits),
        http_client=httpx2.Client(transport=w.transport()),
    )


def claude_event(name: str, payload: dict[str, Any]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def claude_stream(
    text: str, *, stop_reason: str | None = "end_turn", complete: bool = True
) -> bytes:
    third = max(1, len(text) // 3)
    parts = [text[i : i + third] for i in range(0, len(text), third)]
    usage_in = {"input_tokens": 210, "output_tokens": 1}
    body = claude_event(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": MODEL,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": usage_in,
            },
        },
    )
    body += claude_event(
        "content_block_start",
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    )
    for part in parts:
        body += claude_event(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": part},
            },
        )
    if not complete:
        return body
    body += claude_event("content_block_stop", {"type": "content_block_stop", "index": 0})
    body += claude_event(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": 33},
        },
    )
    body += claude_event("message_stop", {"type": "message_stop"})
    return body


def claude_reply(body: bytes, *, chunk: int | None = None) -> Callable[[Any], Any]:
    pieces: Any = chunked(body, chunk) if chunk else [body]
    return lambda _r: httpx2.Response(
        200, headers={"content-type": "text/event-stream"}, content=iter(pieces)
    )


class TestClaudeValidAndRequestShape:
    def test_streamed_message_becomes_a_validated_draft_with_usage(
        self, inputs: DraftInputs
    ) -> None:
        w = wire(httpx2, claude_reply(claude_stream(valid_draft_json(inputs))))
        outcome = claude_adapter(w).draft_outcome(inputs)
        assert outcome.draft.turn_id == TURN_ID
        assert (outcome.input_tokens, outcome.output_tokens) == (210, 33)
        kinds = [e.kind for e in outcome.events]
        assert kinds[0] == "started" and kinds[-1] == "completed" and "delta" in kinds

    def test_request_shape_uses_the_messages_api_with_the_key_in_a_header(
        self, inputs: DraftInputs
    ) -> None:
        w = wire(httpx2, claude_reply(claude_stream(valid_draft_json(inputs))))
        claude_adapter(w, max_output_tokens=90).draft_outcome(inputs)
        (request,) = w.requests
        assert request.method == "POST" and request.url.path == "/v1/messages"
        assert request.url.host == "api.anthropic.com"
        assert request.headers["x-api-key"] == SECRET
        body = w.bodies()[0]
        assert body["model"] == MODEL and body["stream"] is True
        assert body["max_tokens"] == 90
        assert "Respond with ONE JSON object" in body["system"]
        assert [m["role"] for m in body["messages"]] == ["user"]
        assert SECRET not in json.dumps(body)

    def test_sdk_level_retries_are_off_so_the_adapter_owns_the_retry_budget(
        self, inputs: DraftInputs
    ) -> None:
        w = wire(httpx2, status(httpx2, 529))
        adapter = claude_adapter(w, max_attempts=2)
        with pytest.raises(RetriesExhaustedError):
            adapter.draft_outcome(inputs)
        assert len(w.requests) == 2 == adapter.calls_made

    def test_label_and_capabilities_disclose_that_context_leaves_the_machine(self) -> None:
        adapter = claude_adapter(wire(httpx2, status(httpx2, 500)))
        assert adapter.capabilities().transmission == "remote_provider"
        assert "sends context to Anthropic" in adapter.label().label
        assert adapter.label().is_mock is False
        assert SECRET not in repr(adapter.label())

    def test_from_settings_requires_key_and_model_and_guesses_no_default_model(self) -> None:
        with pytest.raises(ProviderConfigError, match="ANTHROPIC_API_KEY"):
            ClaudeAdapter.from_settings(settings_for(anthropic_model=MODEL))
        with pytest.raises(ProviderConfigError, match="ANTHROPIC_API_KEY"):
            ClaudeAdapter.from_settings(settings_for(anthropic_api_key="", anthropic_model=MODEL))
        with pytest.raises(ProviderConfigError, match="ANTHROPIC_MODEL"):
            ClaudeAdapter.from_settings(settings_for(anthropic_api_key=SECRET))
        built = ClaudeAdapter.from_settings(
            settings_for(anthropic_api_key=SECRET, anthropic_model=MODEL)
        )
        assert built.model == MODEL


class TestClaudeStreamsAndDrafts:
    @pytest.mark.parametrize("size", [1, 3, 11, 100])
    def test_events_split_across_network_chunks_are_reassembled(
        self, inputs: DraftInputs, size: int
    ) -> None:
        draft_json = valid_draft_json(inputs, utterance="Try √(2x) ≥ 3 and group the terms.")
        w = wire(httpx2, claude_reply(claude_stream(draft_json), chunk=size))
        outcome = claude_adapter(w).draft_outcome(inputs)
        assert outcome.draft.utterance == "Try √(2x) ≥ 3 and group the terms."
        assert "".join(e.text for e in outcome.events if e.kind == "delta") == draft_json

    def test_a_stream_that_ends_before_message_stop_is_transient_and_retried(
        self, inputs: DraftInputs
    ) -> None:
        full = valid_draft_json(inputs)
        w = wire(
            httpx2,
            claude_reply(claude_stream(full[: len(full) // 2], complete=False)),
            claude_reply(claude_stream(full)),
        )
        outcome = claude_adapter(w).draft_outcome(inputs)
        assert outcome.attempts == 2 and len(w.requests) == 2

    def test_a_stream_that_never_completes_exhausts_instead_of_committing_a_partial(
        self, inputs: DraftInputs
    ) -> None:
        w = wire(httpx2, claude_reply(claude_stream(valid_draft_json(inputs), complete=False)))
        with pytest.raises(RetriesExhaustedError):
            claude_adapter(w, max_attempts=2).draft_outcome(inputs)

    def test_malformed_final_draft_is_rejected_without_a_second_paid_call(
        self, inputs: DraftInputs
    ) -> None:
        w = wire(httpx2, claude_reply(claude_stream("I think you should try grouping.")))
        with pytest.raises(MalformedDraftError):
            claude_adapter(w).draft_outcome(inputs)
        assert len(w.requests) == 1

    def test_stale_draft_for_another_turn_is_rejected(self, inputs: DraftInputs) -> None:
        w = wire(httpx2, claude_reply(claude_stream(valid_draft_json(inputs, turn_id="old"))))
        with pytest.raises(StaleDraftError):
            claude_adapter(w).draft_outcome(inputs)
        assert len(w.requests) == 1

    def test_max_tokens_stop_reason_is_truncation_not_a_draft(self, inputs: DraftInputs) -> None:
        w = wire(
            httpx2,
            claude_reply(claude_stream(valid_draft_json(inputs), stop_reason="max_tokens")),
        )
        with pytest.raises(TruncatedDraftError):
            claude_adapter(w).draft_outcome(inputs)

    def test_oversized_output_is_cut_off_and_rejected(self, inputs: DraftInputs) -> None:
        w = wire(httpx2, claude_reply(claude_stream("x" * 30_000)))
        with pytest.raises(MalformedDraftError, match="size"):
            claude_adapter(w).draft_outcome(inputs)
        assert len(w.requests) == 1


class TestClaudeRetryTimeoutCancel:
    @pytest.mark.parametrize("code", [429, 500, 503, 529])
    def test_transient_statuses_retry_then_succeed(self, inputs: DraftInputs, code: int) -> None:
        w = wire(
            httpx2,
            status(httpx2, code),
            claude_reply(claude_stream(valid_draft_json(inputs))),
        )
        outcome = claude_adapter(w).draft_outcome(inputs)
        assert outcome.attempts == 2 and len(w.requests) == 2

    def test_exhaustion_is_typed_and_bounded(self, inputs: DraftInputs) -> None:
        w = wire(httpx2, status(httpx2, 529))
        with pytest.raises(RetriesExhaustedError) as caught:
            claude_adapter(w, max_attempts=3).draft_outcome(inputs)
        assert caught.value.attempts == 3 and len(w.requests) == 3
        assert SECRET not in str(caught.value) + repr(vars(caught.value))

    def test_retry_after_header_is_honored(self, inputs: DraftInputs) -> None:
        w = wire(
            httpx2,
            status(httpx2, 429, {"retry-after": "0.2"}),
            claude_reply(claude_stream(valid_draft_json(inputs))),
        )
        started = time.monotonic()
        claude_adapter(w).draft_outcome(inputs)
        assert time.monotonic() - started >= 0.19

    @pytest.mark.parametrize("code", [401, 403])
    def test_rejected_credentials_are_not_retried(self, inputs: DraftInputs, code: int) -> None:
        w = wire(httpx2, status(httpx2, code))
        with pytest.raises(ProviderAuthError):
            claude_adapter(w).draft_outcome(inputs)
        assert len(w.requests) == 1

    @pytest.mark.parametrize("code", [400, 404, 413, 422])
    def test_client_errors_are_rejections(self, inputs: DraftInputs, code: int) -> None:
        w = wire(httpx2, status(httpx2, code))
        with pytest.raises(ProviderRejectedError):
            claude_adapter(w).draft_outcome(inputs)
        assert len(w.requests) == 1

    def test_connection_failure_is_transient(self, inputs: DraftInputs) -> None:
        w = wire(httpx2, raising(httpx2.ConnectError("refused " + SECRET)))
        with pytest.raises(RetriesExhaustedError) as caught:
            claude_adapter(w).draft_outcome(inputs)
        assert SECRET not in str(caught.value)
        assert len(w.requests) == 3

    def test_transport_timeout_is_a_timeout_error(self, inputs: DraftInputs) -> None:
        w = wire(httpx2, raising(httpx2.ReadTimeout("slow")))
        with pytest.raises(ProviderTimeoutError):
            claude_adapter(w).draft_outcome(inputs)
        assert len(w.requests) == 1

    def test_default_client_against_blocked_network_is_refused_and_exhausts(
        self, inputs: DraftInputs, no_network: list
    ) -> None:
        adapter = ClaudeAdapter(
            model=MODEL, api_key=SECRET, limits=fast_limits(max_attempts=2, timeout_seconds=5)
        )
        with pytest.raises(RetriesExhaustedError):
            adapter.draft_outcome(inputs)
        assert adapter.calls_made == 2 and no_network

    def test_deadline_between_stream_events_stops_reading(self, inputs: DraftInputs) -> None:
        def slow(_r: Any) -> Any:
            def chunks() -> Iterator[bytes]:
                body = claude_stream(valid_draft_json(inputs))
                events = body.split(b"\n\n")
                for index, event in enumerate(events):
                    if index == 4:
                        time.sleep(0.4)
                    yield event + b"\n\n"

            return httpx2.Response(200, content=chunks())

        adapter = claude_adapter(wire(httpx2, slow), timeout_seconds=0.2)
        with pytest.raises((ProviderTimeoutError, RetriesExhaustedError)):
            adapter.draft_outcome(inputs)

    def test_cancel_before_the_call_sends_nothing(self, inputs: DraftInputs) -> None:
        w = wire(httpx2, claude_reply(claude_stream(valid_draft_json(inputs))))
        token = CancelToken()
        token.cancel()
        with pytest.raises(ProviderCancelledError):
            claude_adapter(w).draft_outcome(with_cancel(inputs, token))
        assert w.requests == []

    def test_cancel_releases_a_blocked_stream_and_nothing_commits(
        self, inputs: DraftInputs
    ) -> None:
        release = threading.Event()
        closed = threading.Event()
        events = claude_stream(valid_draft_json(inputs)).split(b"\n\n")
        first = b"\n\n".join(events[:4]) + b"\n\n"

        class Hanging(httpx2.SyncByteStream):
            def __iter__(self) -> Iterator[bytes]:
                yield first
                release.wait(timeout=10)

            def close(self) -> None:
                closed.set()
                release.set()

        w = wire(httpx2, lambda _r: httpx2.Response(200, stream=Hanging()))
        adapter = claude_adapter(w, timeout_seconds=30.0)
        token = CancelToken()
        seen: list[str] = []
        watched = DraftInputs(
            **{**inputs.__dict__, "cancel": token, "on_event": lambda e: seen.append(e.kind)}
        )
        result: list[BaseException] = []

        def call() -> None:
            try:
                adapter.draft_outcome(watched)
            except BaseException as error:
                result.append(error)

        thread = threading.Thread(target=call)
        thread.start()
        deadline = time.monotonic() + 5
        while not closed.is_set() and time.monotonic() < deadline:
            if "delta" in seen:
                token.cancel("user left")
            time.sleep(0.01)
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert closed.is_set()
        assert [type(e) for e in result] == [ProviderCancelledError]
        assert "completed" not in seen


# ------------------------------ shared remote bounds ------------------------------------


@pytest.mark.parametrize("flavor", ["endpoint", "claude"])
class TestSharedRemoteBounds:
    def adapter(
        self, flavor: str, inputs: DraftInputs, **limits: Any
    ) -> tuple[RemoteAdapter, Wire]:
        if flavor == "endpoint":
            w = wire(httpx, stream_reply(chat_stream(valid_draft_json(inputs))))
            return endpoint_adapter(w, **limits), w
        w = wire(httpx2, claude_reply(claude_stream(valid_draft_json(inputs))))
        return claude_adapter(w, **limits), w

    def test_a_request_over_the_character_ceiling_is_refused_without_a_call(
        self, flavor: str, inputs: DraftInputs
    ) -> None:
        limit = inputs.request.request_chars - 1
        adapter, w = self.adapter(flavor, inputs, max_request_chars=limit)
        with pytest.raises(RequestTooLargeError):
            adapter.draft_outcome(inputs)
        assert w.requests == []

    def test_a_request_exactly_at_the_ceiling_is_sent(
        self, flavor: str, inputs: DraftInputs
    ) -> None:
        limit = inputs.request.request_chars
        adapter, w = self.adapter(flavor, inputs, max_request_chars=limit)
        adapter.draft_outcome(inputs)
        assert len(w.requests) == 1

    def test_only_a_bounded_number_of_remote_calls_run_at_once(
        self, flavor: str, inputs: DraftInputs
    ) -> None:
        adapter, _ = self.adapter(flavor, inputs)
        held = [adapter._slots.acquire(blocking=False) for _ in range(MAX_CONCURRENT_CALLS)]
        assert all(held)
        with pytest.raises(ProviderBusyError):
            adapter.draft_outcome(inputs)

    def test_a_tighter_budget_request_fits_the_default_ceiling(
        self, flavor: str, database: Database
    ) -> None:
        small = make_inputs(database, budget=ProviderBudget(max_output_tokens=64))
        adapter, w = self.adapter(flavor, small)
        adapter.draft_outcome(small)
        sent = w.bodies()[0]["max_tokens"]
        assert sent == 64


def test_reply_helper_echoes_the_contract_fixed_fields(inputs: DraftInputs) -> None:
    from app.inference.events import with_contract

    messages = [
        {"role": m.role, "content": m.content}
        for m in with_contract(inputs.request.messages, inputs.plan, inputs.session_revision)
    ]
    body = json.loads(reply_for_request(messages))
    assert body["turn_id"] == TURN_ID and body["session_revision"] == inputs.session_revision
