"""Production adapters inside the real API, coordinator and persistence.

Remote adapters are real (httpx / anthropic SDK) over in-process transport fixtures, with
outbound sockets blocked. These tests show that only a complete, current, validated draft
commits, that failures leave no partial effects, that remote providers are disabled by
default and disclose transmission, and that nothing falls back to another provider.
"""

import json
import threading
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.database import Database
from app.inference import factory
from app.inference.claude import ClaudeAdapter
from app.inference.endpoint import EndpointAdapter
from app.inference.local import LocalTransformersAdapter
from app.inference.providers import MockTutorProvider
from app.main import create_app
from tests.conftest import bootstrap
from tests.provider_fixtures import (
    SECRET,
    fast_limits,
    reply_for_request,
)
from tests.test_remote_adapters import (
    chat_stream,
    claude_event,
    claude_stream,
    stream_reply,
)
from tests.test_tutor_turns import check_in, key, post_turn, start_session, table_counts

ENV_NAMES = (
    "TUTOR_PROVIDER",
    "EXTERNAL_INTEGRATIONS_ENABLED",
    "TUTOR_LOCAL_MODEL_LOAD_ENABLED",
    "TUTOR_ENDPOINT_BASE_URL",
    "TUTOR_ENDPOINT_MODEL",
    "TUTOR_ENDPOINT_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "TUTOR_ENV_FILE",
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, no_network: list) -> Iterator[list]:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    factory.reset_adapters()
    yield no_network
    factory.reset_adapters()


def server_reply(messages: list[dict[str, str]], *, utterance: str = "Let's begin.") -> str:
    return reply_for_request(messages, utterance)


def endpoint_with(handler: Callable[[httpx.Request], httpx.Response]) -> EndpointAdapter:
    return EndpointAdapter(
        base_url="https://llm.example.test/v1",
        model="fixture-model",
        api_key=SECRET,
        limits=fast_limits(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )


def model_stream(request: httpx.Request, mutate: Callable[[str], str] = lambda s: s) -> bytes:
    body = json.loads(request.content)
    return chat_stream(mutate(server_reply(body["messages"])))


@pytest.fixture
def use_adapter(monkeypatch: pytest.MonkeyPatch) -> Callable[[Any], None]:
    def install(adapter: Any) -> None:
        monkeypatch.setattr("app.tutor.coordinator.get_provider", lambda settings: adapter)

    return install


class TestCoordinatorCommitsOnlyCompleteCurrentDrafts:
    def test_complete_valid_endpoint_draft_commits_with_an_honest_non_mock_label(
        self, client: TestClient, use_adapter: Callable[[Any], None]
    ) -> None:
        use_adapter(endpoint_with(lambda request: stream_reply(model_stream(request))(request)))
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        response = post_turn(
            client, headers, session_id, "check-in", {"expected_revision": 0}, key("ok")
        )
        result = response.json()
        assert result["status"] == "committed"
        assert result["utterance"] == "Let's begin."
        assert result["provider"]["is_mock"] is False
        assert result["provider"]["name"] == "endpoint"
        assert "sends context to a remote server" in result["provider"]["label"]

    def test_complete_valid_work_draft_commits_hint_drawing_and_assessment(
        self, client: TestClient, database: Database, use_adapter: Callable[[Any], None]
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        before = table_counts(database, learner_id)
        use_adapter(endpoint_with(lambda request: stream_reply(model_stream(request))(request)))
        result = post_turn(
            client,
            headers,
            session_id,
            "work",
            {"expected_revision": 1, "text": "2x + 3 = 14"},
            key("work-ok"),
        ).json()
        assert result["status"] == "committed", result["rejections"]
        after = table_counts(database, learner_id)
        assert after["hints"] == before["hints"] + 1
        assert result["provider"]["is_mock"] is False

    def test_the_draft_contract_asks_for_the_evidence_ids_the_coordinator_requires(
        self, database: Database
    ) -> None:
        from app.inference.events import draft_contract_text
        from tests.provider_fixtures import make_inputs

        inputs = make_inputs(database)
        assert inputs.plan.required_evidence_ids, "a check-in plan requires grounding"
        text = draft_contract_text(inputs.plan, inputs.session_revision)
        for evidence_id in inputs.plan.required_evidence_ids:
            assert json.dumps(evidence_id) in text

    @pytest.mark.parametrize(
        ("name", "mutate"),
        [
            ("truncated", lambda text: text[: len(text) // 2]),
            ("prose", lambda text: "Great question! Try grouping."),
            ("stale_turn", lambda text: text.replace('"turn_id": "', '"turn_id": "old-', 1)),
            (
                "unknown_field_removed",
                lambda text: json.dumps(
                    {k: v for k, v in json.loads(text).items() if k != "utterance"}
                ),
            ),
        ],
    )
    def test_unusable_endpoint_output_fails_the_turn_with_no_partial_effects(
        self,
        client: TestClient,
        database: Database,
        use_adapter: Callable[[Any], None],
        name: str,
        mutate: Callable[[str], str],
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        check_in(client, headers, session_id)
        before = table_counts(database, learner_id)
        use_adapter(
            endpoint_with(lambda request: stream_reply(model_stream(request, mutate))(request))
        )
        response = post_turn(
            client,
            headers,
            session_id,
            "work",
            {"expected_revision": 1, "text": "2x + 3 = 14"},
            key(name),
        )
        result = response.json()
        assert response.status_code == 200
        assert result["status"] == "failed", name
        assert result["rejections"][0]["code"] == "provider_error"
        assert result["utterance"] is None and result["drawings"] == []
        after = table_counts(database, learner_id)
        for effect in ("hints", "assessments", "scene_objects", "memory"):
            assert after[effect] == before[effect], effect

    def test_partial_stream_followed_by_exhaustion_commits_nothing(
        self, client: TestClient, database: Database, use_adapter: Callable[[Any], None]
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        before = table_counts(database, learner_id)
        use_adapter(endpoint_with(lambda request: httpx.Response(503, json={})))
        response = post_turn(
            client, headers, session_id, "check-in", {"expected_revision": 0}, key("down")
        )
        assert response.json()["status"] == "failed"
        assert table_counts(database, learner_id)["hints"] == before["hints"]

    def test_draft_arriving_after_the_session_moved_on_is_superseded_not_committed(
        self,
        client: TestClient,
        database: Database,
        use_adapter: Callable[[Any], None],
    ) -> None:
        learner_id, headers = bootstrap(client)
        session_id = start_session(client, headers)
        entered, release = threading.Event(), threading.Event()

        def handler(request: httpx.Request) -> httpx.Response:
            entered.set()
            assert release.wait(timeout=15)
            return stream_reply(model_stream(request))(request)

        use_adapter(endpoint_with(handler))
        outcome: dict[str, Any] = {}
        before = table_counts(database, learner_id)

        def run() -> None:
            outcome["response"] = post_turn(
                client, headers, session_id, "check-in", {"expected_revision": 0}, key("slow")
            )

        thread = threading.Thread(target=run)
        thread.start()
        try:
            assert entered.wait(timeout=15)
            assert client.post(f"/sessions/{session_id}/end", headers=headers).status_code == 200
        finally:
            release.set()
            thread.join(timeout=15)
        result = outcome["response"].json()
        assert result["status"] == "superseded"
        assert result["utterance"] is None
        assert result["rejections"][0]["code"] == "revision_changed"
        assert table_counts(database, learner_id)["hints"] == before["hints"]

    def test_claude_draft_commits_through_the_same_path(
        self, client: TestClient, use_adapter: Callable[[Any], None]
    ) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            body = json.loads(request.content)
            messages = [{"role": "system", "content": body["system"]}, *body["messages"]]
            return httpx2.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=iter([claude_stream(server_reply(messages, utterance="Claude says hi."))]),
            )

        adapter = ClaudeAdapter(
            model="fixture-claude",
            api_key=SECRET,
            limits=fast_limits(),
            http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        )
        use_adapter(adapter)
        _, headers = bootstrap(client)
        session_id = start_session(client, headers)
        result = post_turn(
            client, headers, session_id, "check-in", {"expected_revision": 0}, key("cl")
        ).json()
        assert result["status"] == "committed" and result["utterance"] == "Claude says hi."
        assert result["provider"]["name"] == "claude"
        assert "sends context to Anthropic" in result["provider"]["label"]
        assert SECRET not in json.dumps(result)


def api_client(database_url: str, **overrides: object) -> TestClient:
    settings = Settings.model_validate({"database_url": database_url, **overrides})
    return TestClient(create_app(settings))


class TestDisabledByDefaultAndDisclosure:
    @pytest.mark.parametrize("provider", ["claude", "endpoint", "transformers"])
    def test_selected_but_not_enabled_provider_is_refused_with_503_and_nothing_is_built(
        self, seeded_db_url: str, provider: str, no_network: list
    ) -> None:
        settings = {
            "tutor_provider": provider,
            "anthropic_api_key": SECRET,
            "anthropic_model": "m",
            "tutor_endpoint_base_url": "https://llm.example.test/v1",
            "tutor_endpoint_model": "m",
            "tutor_endpoint_api_key": SECRET,
        }
        with api_client(seeded_db_url, **settings) as client:
            _, headers = bootstrap(client)
            session_id = start_session(client, headers)
            response = post_turn(
                client, headers, session_id, "check-in", {"expected_revision": 0}, key("off")
            )
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "provider_unavailable"
            assert SECRET not in response.text
            health = client.get("/health/model")
            assert health.json()["state"] == "disabled" and health.json()["ready"] is False
            assert SECRET not in health.text
        assert factory.peek_adapter(Settings.model_validate({"tutor_provider": provider})) is None
        assert no_network == []

    def test_mock_is_the_default_and_is_labeled_as_not_a_language_model(
        self, client: TestClient
    ) -> None:
        body = client.get("/health/model").json()
        assert body["provider"] == "mock" and body["is_mock"] is True
        assert "not a language model" in body["label"]

    @pytest.mark.parametrize(
        ("overrides", "state", "mentions"),
        [
            (
                {"tutor_provider": "claude", "external_integrations_enabled": True},
                "unverified",
                "ANTHROPIC_API_KEY",
            ),
            (
                {"tutor_provider": "endpoint", "external_integrations_enabled": True},
                "unverified",
                "TUTOR_ENDPOINT_BASE_URL",
            ),
        ],
    )
    def test_enabled_but_unconfigured_remote_says_what_is_missing(
        self, seeded_db_url: str, overrides: dict[str, object], state: str, mentions: str
    ) -> None:
        body = api_client(seeded_db_url, **overrides).get("/health/model").json()
        assert body["state"] == state and body["ready"] is False
        assert mentions in body["detail"] and "not configured" in body["label"]

    @pytest.mark.parametrize(
        ("overrides", "model"),
        [
            (
                {
                    "tutor_provider": "claude",
                    "anthropic_api_key": SECRET,
                    "anthropic_model": "fixture-claude",
                },
                "fixture-claude",
            ),
            (
                {
                    "tutor_provider": "endpoint",
                    "tutor_endpoint_base_url": "https://llm.example.test/v1",
                    "tutor_endpoint_model": "fixture-endpoint",
                    "tutor_endpoint_api_key": SECRET,
                },
                "fixture-endpoint",
            ),
        ],
    )
    def test_configured_remote_is_unverified_discloses_transmission_and_hides_the_key(
        self, seeded_db_url: str, overrides: dict[str, object], model: str, no_network: list
    ) -> None:
        client = api_client(seeded_db_url, external_integrations_enabled=True, **overrides)
        response = client.get("/health/model")
        body = response.json()
        assert body["state"] == "unverified" and body["ready"] is False
        assert body["model_id"] == model
        assert body["transmission"] == "remote_provider"
        assert "sent to it when used" in body["detail"]
        assert SECRET not in response.text
        assert no_network == [], "readiness must not contact the provider"

    def test_local_readiness_names_the_pinned_revision_and_in_process_transmission(
        self, seeded_db_url: str
    ) -> None:
        body = (
            api_client(
                seeded_db_url, tutor_provider="transformers", tutor_local_model_load_enabled=True
            )
            .get("/health/model")
            .json()
        )
        assert body["model_revision"] == "12fd25f77366fa6b3b4b768ec3050bf629380bac"
        assert body["transmission"] == "this_process"
        assert body["state"] == "not_loaded"

    def test_settings_repr_and_dump_do_not_reveal_secrets(self) -> None:
        settings = Settings.model_validate(
            {"anthropic_api_key": SECRET, "tutor_endpoint_api_key": SECRET}
        )
        assert SECRET not in repr(settings)
        assert SECRET not in settings.model_dump_json()


class TestNoSilentFallback:
    def test_a_failing_claude_turn_fails_and_never_reaches_mock_or_another_provider(
        self,
        seeded_db_url: str,
        monkeypatch: pytest.MonkeyPatch,
        no_network: list,
    ) -> None:
        mock_calls: list[object] = []
        monkeypatch.setattr(MockTutorProvider, "draft", lambda self, i: mock_calls.append(i))
        endpoint_calls: list[object] = []
        monkeypatch.setattr(
            EndpointAdapter, "draft_outcome", lambda self, i: endpoint_calls.append(i)
        )
        sdk_requests: list[httpx2.Request] = []

        def refuse(request: httpx2.Request) -> httpx2.Response:
            sdk_requests.append(request)
            return httpx2.Response(
                529,
                json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}},
            )

        real_from_settings = ClaudeAdapter.from_settings
        monkeypatch.setattr(
            ClaudeAdapter,
            "from_settings",
            classmethod(
                lambda cls, settings, **_k: real_from_settings.__func__(  # type: ignore[attr-defined]
                    cls,
                    settings.model_copy(
                        update={
                            "tutor_remote_backoff_seconds": 0.0,
                        }
                    ),
                    http_client=httpx2.Client(transport=httpx2.MockTransport(refuse)),
                )
            ),
        )
        with api_client(
            seeded_db_url,
            tutor_provider="claude",
            external_integrations_enabled=True,
            anthropic_api_key=SECRET,
            anthropic_model="fixture-claude",
            tutor_remote_max_attempts=2,
            tutor_remote_backoff_seconds=0.0,
        ) as client:
            _, headers = bootstrap(client)
            session_id = start_session(client, headers)
            response = post_turn(
                client, headers, session_id, "check-in", {"expected_revision": 0}, key("fb")
            )
        result = response.json()
        assert result["status"] == "failed"
        assert result["provider"]["name"] == "claude" and result["provider"]["is_mock"] is False
        assert len(sdk_requests) == 2
        assert mock_calls == [] and endpoint_calls == []
        assert no_network == []

    def test_factory_never_builds_a_different_provider_than_the_one_configured(self) -> None:
        settings = Settings.model_validate(
            {
                "database_url": "sqlite://",
                "tutor_provider": "claude",
                "external_integrations_enabled": True,
                "anthropic_api_key": SECRET,
                "anthropic_model": "fixture-claude",
            }
        )
        adapter = factory.adapter_for(settings)
        assert isinstance(adapter, ClaudeAdapter)
        assert factory.adapter_for(settings) is adapter
        assert not isinstance(adapter, LocalTransformersAdapter | EndpointAdapter)
        other = settings.model_copy(update={"tutor_provider": "endpoint"})
        assert factory.peek_adapter(other) is None

    def test_misconfigured_remote_raises_a_typed_error_instead_of_defaulting(self) -> None:
        from app.inference.errors import ProviderConfigError

        settings = Settings.model_validate(
            {
                "database_url": "sqlite://",
                "tutor_provider": "claude",
                "external_integrations_enabled": True,
                "anthropic_api_key": SECRET,
            }
        )
        with pytest.raises(ProviderConfigError, match="ANTHROPIC_MODEL"):
            factory.adapter_for(settings)


def test_claude_event_helper_builds_decodable_sse() -> None:
    assert claude_event("ping", {"type": "ping"}).startswith(b"event: ping\ndata: ")
