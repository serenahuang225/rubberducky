"""The production Daytona adapter against the SDK-boundary fixture in ``fake_daytona``.

Covers pass, failed checks, malformed output, creation failure, timeout and cancellation, and
asserts the exact sandbox IDs created and deleted on every path, with unrelated sandboxes in
the same fake account never touched. Transport fixtures only: no Daytona service is involved.
"""

import asyncio
import inspect
import json
import time
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.interactives import trusted_checks
from app.interactives.daytona_checks import (
    COMMAND,
    RUN_LABEL,
    SCRIPT_NAME,
    SPEC_NAME,
    DaytonaCheckConfig,
    DaytonaTrustedChecker,
    SandboxCheckError,
    canonical_spec_json,
    default_client_factory,
)
from app.interactives.endpoints import validate_daytona_api_url
from app.interactives.errors import InteractiveError
from app.interactives.fallback import DISTRIBUTION_FALLBACK, GROUPING_FALLBACK
from app.schemas.interactives import ExplanationSpec
from tests.fake_daytona import FakeAsyncDaytona, FakeDaytonaError, FakeDaytonaService
from tests.interactive_fixtures import unvalidated_spec


def config(**overrides: Any) -> DaytonaCheckConfig:
    fields: dict[str, Any] = {
        "api_key": "dtn-test-key-0123456789",
        "api_url": "https://app.daytona.io/api",
        "target": "us",
        "create_timeout_seconds": 5.0,
        "exec_timeout_seconds": 5,
        "cleanup_timeout_seconds": 5.0,
    }
    return DaytonaCheckConfig(**{**fields, **overrides})


def checker(service: FakeDaytonaService, **overrides: Any) -> DaytonaTrustedChecker:
    return DaytonaTrustedChecker(
        config(),
        client_factory=service.client,
        upload_allowance_seconds=overrides.pop("upload_allowance_seconds", 0.3),
        **overrides,
    )


def service_with_decoys() -> FakeDaytonaService:
    service = FakeDaytonaService()
    service.add_decoy("sbx-other-team")
    service.add_decoy("sbx-same-label-key", {RUN_LABEL: "some-other-run"})
    return service


def assert_decoys_untouched(service: FakeDaytonaService) -> None:
    assert {"sbx-other-team", "sbx-same-label-key"} <= set(service.sandboxes)
    assert "sbx-other-team" not in service.deleted_ids
    assert "sbx-same-label-key" not in service.deleted_ids


def out_of_range_spec() -> ExplanationSpec:
    return unvalidated_spec(
        GROUPING_FALLBACK, manipulative={"groups": {"min": 1, "max": 99, "initial": 3}}
    )


def test_passing_candidate_runs_the_uploaded_trusted_script_and_deletes_its_sandbox() -> None:
    service = service_with_decoys()
    result = asyncio.run(checker(service).check(DISTRIBUTION_FALLBACK))
    assert result.report.passed
    assert [c.name for c in result.report.checks] == list(trusted_checks.CHECK_NAMES)
    assert result.sandbox_ids_created == ("sbx-created-1",)
    assert result.sandbox_ids_deleted == ("sbx-created-1",)
    assert service.created_ids == service.deleted_ids == ["sbx-created-1"]
    assert "sbx-created-1" not in service.sandboxes
    assert_decoys_untouched(service)
    assert service.exec_calls == [COMMAND]
    assert service.client_closed == 1


def test_sandbox_receives_the_repository_script_and_exactly_the_candidate_spec() -> None:
    service = FakeDaytonaService()
    captured: dict[str, bytes] = {}
    real_client = service.client

    def capturing_client(cfg: object = None) -> FakeAsyncDaytona:
        client = real_client(cfg)
        original_delete = client.delete

        async def delete(sandbox: Any, timeout: float = 60, wait: bool = False) -> None:
            captured.update(sandbox.files)
            await original_delete(sandbox, timeout, wait)

        client.delete = delete  # type: ignore[method-assign]
        return client

    asyncio.run(
        DaytonaTrustedChecker(config(), client_factory=capturing_client).check(GROUPING_FALLBACK)
    )
    assert captured[SCRIPT_NAME] == Path(trusted_checks.__file__).read_bytes()
    assert captured[SPEC_NAME].decode() == canonical_spec_json(GROUPING_FALLBACK)
    assert json.loads(captured[SPEC_NAME]) == GROUPING_FALLBACK.model_dump(mode="json")


def test_sandbox_is_private_ephemeral_and_labeled_with_a_unique_run_id() -> None:
    service = FakeDaytonaService()
    asyncio.run(checker(service).check(GROUPING_FALLBACK))
    asyncio.run(checker(service).check(GROUPING_FALLBACK))
    first, second = service.create_params
    for params in (first, second):
        assert params.public is False
        assert params.ephemeral is True
        assert params.network_block_all is True
        assert params.ttl_minutes and params.ttl_minutes <= 15
        assert params.auto_stop_interval == 1
        assert not params.env_vars and not params.secrets and not params.volumes
    assert first.labels[RUN_LABEL] != second.labels[RUN_LABEL]


def test_failed_invariants_are_reported_and_the_sandbox_is_still_deleted() -> None:
    service = service_with_decoys()
    # The real script rejects this out-of-range spec in the sandbox itself.
    result = asyncio.run(checker(service).check(out_of_range_spec()))
    assert result.report.passed is False
    failed = {c.name for c in result.report.checks if not c.passed}
    assert "bounds" in failed
    assert service.deleted_ids == service.created_ids == ["sbx-created-1"]
    assert_decoys_untouched(service)


@pytest.mark.parametrize("mode", ["garbage", "wrong_digest", "exit_mismatch", "oversize_report"])
def test_malformed_or_mismatched_sandbox_output_is_never_trusted(mode: str) -> None:
    service = service_with_decoys()
    service.exec_mode = mode
    with pytest.raises(SandboxCheckError) as caught:
        asyncio.run(checker(service).check(DISTRIBUTION_FALLBACK))
    assert caught.value.code == "checks_malformed"
    assert caught.value.created == caught.value.deleted == ("sbx-created-1",)
    assert_decoys_untouched(service)


def test_sdk_failure_text_never_reaches_the_error() -> None:
    service = service_with_decoys()
    service.exec_mode = "exec_error"
    with pytest.raises(SandboxCheckError) as caught:
        asyncio.run(checker(service).check(DISTRIBUTION_FALLBACK))
    assert caught.value.code == "checks_unavailable"
    assert "sk-leaky" not in str(caught.value) and "sk-leaky" not in repr(caught.value.__cause__)
    assert caught.value.deleted == ("sbx-created-1",)


def test_creation_error_without_a_sandbox_deletes_nothing() -> None:
    service = service_with_decoys()
    service.create_mode = "error"
    with pytest.raises(SandboxCheckError) as caught:
        asyncio.run(checker(service).check(DISTRIBUTION_FALLBACK))
    assert caught.value.code == "checks_unavailable"
    assert caught.value.created == () and caught.value.deleted == ()
    assert service.deleted_ids == []
    assert_decoys_untouched(service)


def test_creation_error_after_the_service_made_a_sandbox_deletes_that_exact_id() -> None:
    service = service_with_decoys()
    service.create_mode = "orphan_error"
    with pytest.raises(SandboxCheckError) as caught:
        asyncio.run(checker(service).check(DISTRIBUTION_FALLBACK))
    assert caught.value.code == "checks_unavailable"
    assert caught.value.created == caught.value.deleted == ("sbx-created-1",)
    assert service.deleted_ids == ["sbx-created-1"]
    assert_decoys_untouched(service)


def test_failed_label_lookup_does_not_widen_cleanup_to_other_sandboxes() -> None:
    service = service_with_decoys()
    service.create_mode = "orphan_error"
    service.list_error = True
    with pytest.raises(SandboxCheckError):
        asyncio.run(checker(service).check(DISTRIBUTION_FALLBACK))
    assert service.deleted_ids == []
    assert_decoys_untouched(service)


def test_exec_timeout_is_bounded_and_deletes_the_created_sandbox() -> None:
    service = service_with_decoys()
    service.exec_mode = "hang"
    started = time.monotonic()
    with pytest.raises(SandboxCheckError) as caught:
        asyncio.run(
            DaytonaTrustedChecker(
                config(create_timeout_seconds=0.2, exec_timeout_seconds=1),
                client_factory=service.client,
                upload_allowance_seconds=0.2,
            ).check(DISTRIBUTION_FALLBACK)
        )
    assert time.monotonic() - started < 10
    assert caught.value.code == "checks_timeout"
    assert caught.value.created == caught.value.deleted == ("sbx-created-1",)
    assert_decoys_untouched(service)


def test_sdk_reported_timeout_maps_to_checks_timeout() -> None:
    import daytona

    service = service_with_decoys()
    service.exec_mode = "fixture_timeout"
    service.timeout_error = lambda: daytona.DaytonaProcessExecutionTimeoutError("took too long")
    with pytest.raises(SandboxCheckError) as caught:
        asyncio.run(checker(service).check(DISTRIBUTION_FALLBACK))
    assert caught.value.code == "checks_timeout"
    assert caught.value.deleted == ("sbx-created-1",)


def test_create_timeout_finds_and_deletes_the_sandbox_that_was_being_created() -> None:
    service = service_with_decoys()
    service.create_mode = "orphan_hang"
    with pytest.raises(SandboxCheckError) as caught:
        asyncio.run(
            DaytonaTrustedChecker(
                config(create_timeout_seconds=0.2, exec_timeout_seconds=1),
                client_factory=service.client,
                upload_allowance_seconds=0.1,
            ).check(DISTRIBUTION_FALLBACK)
        )
    assert caught.value.code == "checks_timeout"
    assert caught.value.created == caught.value.deleted == ("sbx-created-1",)
    assert_decoys_untouched(service)


def _cancel_during(mode_field: str, mode: str) -> FakeDaytonaService:
    service = service_with_decoys()
    setattr(service, mode_field, mode)

    async def scenario() -> None:
        task = asyncio.create_task(
            DaytonaTrustedChecker(
                config(create_timeout_seconds=30, exec_timeout_seconds=30),
                client_factory=service.client,
            ).check(DISTRIBUTION_FALLBACK)
        )
        deadline = time.monotonic() + 5
        while not service.created_ids:
            assert time.monotonic() < deadline
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    return service


def test_cancel_during_exec_deletes_the_created_sandbox_before_propagating() -> None:
    service = _cancel_during("exec_mode", "hang")
    assert service.created_ids == service.deleted_ids == ["sbx-created-1"]
    assert service.client_closed == 1
    assert_decoys_untouched(service)


def test_cancel_during_create_deletes_the_unacknowledged_sandbox_by_its_exact_id() -> None:
    service = _cancel_during("create_mode", "orphan_hang")
    assert service.created_ids == service.deleted_ids == ["sbx-created-1"]
    assert_decoys_untouched(service)


def test_a_delete_that_fails_is_a_cleanup_error_not_a_passing_result() -> None:
    service = service_with_decoys()
    service.delete_failures = {"sbx-created-1"}
    with pytest.raises(SandboxCheckError) as caught:
        asyncio.run(checker(service).check(DISTRIBUTION_FALLBACK))
    assert caught.value.code == "cleanup_failed"
    assert caught.value.created == ("sbx-created-1",)
    assert caught.value.deleted == ()
    assert "sbx-created-1" in service.sandboxes
    assert_decoys_untouched(service)


def test_cleanup_failure_after_a_failed_check_still_reports_the_undeleted_id() -> None:
    service = service_with_decoys()
    service.exec_mode = "garbage"
    service.delete_failures = {"sbx-created-1"}
    with pytest.raises(SandboxCheckError) as caught:
        asyncio.run(checker(service).check(DISTRIBUTION_FALLBACK))
    assert caught.value.code == "cleanup_failed"
    assert caught.value.created == ("sbx-created-1",) and caught.value.deleted == ()


def test_an_unverifiable_label_lookup_is_a_cleanup_error() -> None:
    service = service_with_decoys()
    service.create_mode = "orphan_error"
    service.list_error = True
    with pytest.raises(SandboxCheckError) as caught:
        asyncio.run(checker(service).check(DISTRIBUTION_FALLBACK))
    assert caught.value.code == "cleanup_failed"
    assert caught.value.created == () and caught.value.deleted == ()


def test_oversize_candidate_is_refused_before_any_client_exists() -> None:
    created_clients: list[object] = []

    def factory(cfg: object) -> Any:
        created_clients.append(cfg)
        raise AssertionError("no client may be built for an oversize payload")

    big = unvalidated_spec(GROUPING_FALLBACK, caption="word " * 600)
    with pytest.raises(SandboxCheckError) as caught:
        asyncio.run(DaytonaTrustedChecker(config(), client_factory=factory).check(big))
    assert caught.value.code == "oversize_candidate"
    assert created_clients == []


def test_unavailable_service_is_reported_not_papered_over() -> None:
    def factory(_cfg: object) -> Any:
        raise FakeDaytonaError("cannot reach host")

    with pytest.raises(SandboxCheckError) as caught:
        asyncio.run(
            DaytonaTrustedChecker(config(), client_factory=factory).check(GROUPING_FALLBACK)
        )
    assert caught.value.code == "checks_unavailable"
    assert caught.value.created == () and "cannot reach" not in str(caught.value)


class TestEndpointAndConfig:
    @pytest.mark.parametrize(
        "url",
        [
            "http://app.daytona.io/api",
            "https://evil.example/api",
            "https://app.daytona.io.evil.example/api",
            "https://user:secret@app.daytona.io/api",
            "https://app.daytona.io:8443/api",
            "https://notdaytona.io/api",
            "ftp://app.daytona.io/api",
            "",
        ],
    )
    def test_hosts_outside_daytona_are_rejected_before_a_key_is_attached(self, url: str) -> None:
        with pytest.raises(ValueError, match="Daytona API URL") as caught:
            validate_daytona_api_url(url)
        assert "secret" not in str(caught.value)
        with pytest.raises(ValueError, match="Daytona API URL"):
            default_client_factory(config(api_url=url))

    def test_default_and_regional_daytona_hosts_pass(self) -> None:
        assert validate_daytona_api_url("https://app.daytona.io/api") == "app.daytona.io"
        assert validate_daytona_api_url("https://eu.app.daytona.io/api") == "eu.app.daytona.io"

    def test_settings_without_a_key_or_with_a_bad_url_are_not_configured(self) -> None:
        for settings in (
            Settings(daytona_checks_enabled=True),
            Settings(daytona_api_key=SecretStr("k" * 12), daytona_api_url="https://evil.example"),
        ):
            with pytest.raises(InteractiveError) as caught:
                DaytonaCheckConfig.from_settings(settings)
            assert caught.value.code == "not_configured"

    def test_settings_become_an_explicit_config(self) -> None:
        cfg = DaytonaCheckConfig.from_settings(
            Settings(daytona_api_key=SecretStr("dtn-secret-key-123"), daytona_target="eu")
        )
        assert cfg.api_key == "dtn-secret-key-123" and cfg.target == "eu"
        assert cfg.api_url == "https://app.daytona.io/api"

    def test_real_sdk_client_is_built_from_explicit_values_without_network_or_env_fallback(
        self, monkeypatch: pytest.MonkeyPatch, no_network: list[tuple[str, object]]
    ) -> None:
        monkeypatch.setenv("DAYTONA_API_KEY", "dtn-env-key-should-not-be-used")
        monkeypatch.setenv("DAYTONA_API_URL", "https://evil.example/api")

        async def build() -> tuple[str, str | None]:
            client = default_client_factory(config())
            try:
                return str(getattr(client, "_api_url", "")), getattr(client, "_api_key", None)
            finally:
                await client.close()

        url, key = asyncio.run(build())
        assert url == "https://app.daytona.io/api"
        assert key == "dtn-test-key-0123456789"
        assert no_network == []


class TestSdkSignatures:
    """The fixture must expose the same call shapes as the installed SDK."""

    @staticmethod
    def shape(function: Any) -> list[tuple[str, Any, Any]]:
        params = inspect.signature(function).parameters.values()
        return [(p.name, p.kind, p.default) for p in params if p.name != "self"]

    def test_client_methods_match_the_installed_sdk(self) -> None:
        from daytona import AsyncDaytona

        for name in ("create", "delete", "list", "close"):
            real = self.shape(getattr(AsyncDaytona, name))
            fake = self.shape(getattr(FakeAsyncDaytona, name))
            assert fake == real, name

    def test_sandbox_file_and_process_methods_match_the_installed_sdk(self) -> None:
        from daytona import AsyncSandbox
        from daytona._async.filesystem import AsyncFileSystem
        from daytona._async.process import AsyncProcess

        from tests.fake_daytona import FakeFileSystem, FakeProcess

        assert self.shape(FakeFileSystem.upload_file) == self.shape(AsyncFileSystem.upload_file)
        assert self.shape(FakeProcess.exec) == self.shape(AsyncProcess.exec)
        assert {"fs", "process", "id", "labels"} <= set(AsyncSandbox.model_fields) | {
            "fs",
            "process",
        }

    def test_create_params_are_accepted_by_the_real_sdk_model(self) -> None:
        from daytona import CreateSandboxFromSnapshotParams

        params = DaytonaTrustedChecker._create_params("run-1")
        assert isinstance(params, CreateSandboxFromSnapshotParams)
        assert params.labels == {RUN_LABEL: "run-1"}
