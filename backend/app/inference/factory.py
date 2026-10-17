"""Builds and caches the configured production adapter.

``adapter_for`` is called on every turn, so adapters are cached per process: the local model
is therefore loaded once, and remote SDK clients are reused. Building an adapter never loads
weights or contacts a provider. A provider that is disabled or incompletely configured raises
a typed :class:`ProviderUnavailableError` subclass; there is never a fallback to another
provider, and in particular never to a paid one.
"""

import threading

from app.config import Settings
from app.inference.adapter import DraftAdapter
from app.inference.errors import ProviderDisabledError, ProviderUnavailableError

_lock = threading.Lock()
_adapters: dict[tuple[object, ...], DraftAdapter] = {}


def _key(settings: Settings) -> tuple[object, ...]:
    provider = settings.tutor_provider
    if provider == "transformers":
        return (
            provider,
            settings.tutor_local_model_id,
            settings.tutor_local_model_revision,
            settings.tutor_local_device,
            settings.tutor_local_dtype,
            settings.tutor_local_allow_download,
            settings.tutor_local_context_window_tokens,
            settings.tutor_local_max_new_tokens,
            settings.tutor_local_max_queue,
            settings.tutor_local_timeout_seconds,
        )
    remote = (
        settings.tutor_remote_timeout_seconds,
        settings.tutor_remote_max_attempts,
        settings.tutor_remote_backoff_seconds,
        settings.tutor_remote_max_output_tokens,
        settings.tutor_remote_max_request_chars,
    )
    if provider == "claude":
        key = settings.anthropic_api_key
        secret = key.get_secret_value() if key else None
        return (provider, settings.anthropic_model, secret, *remote)
    key = settings.tutor_endpoint_api_key
    return (
        provider,
        settings.tutor_endpoint_base_url,
        settings.tutor_endpoint_model,
        key.get_secret_value() if key else None,
        settings.tutor_endpoint_streaming,
        *remote,
    )


def _build(settings: Settings) -> DraftAdapter:
    provider = settings.tutor_provider
    if provider == "transformers":
        if not settings.tutor_local_model_load_enabled:
            raise ProviderDisabledError(
                provider, "local model loading is opt-in (TUTOR_LOCAL_MODEL_LOAD_ENABLED)"
            )
        from app.inference.hf_transformers import load_transformers_model
        from app.inference.local import LocalModelConfig, LocalTransformersAdapter

        return LocalTransformersAdapter(
            LocalModelConfig.from_settings(settings), load_transformers_model
        )
    if provider in ("claude", "endpoint"):
        if not settings.external_integrations_enabled:
            raise ProviderDisabledError(
                provider, "remote providers require EXTERNAL_INTEGRATIONS_ENABLED=true"
            )
        if provider == "claude":
            from app.inference.claude import ClaudeAdapter

            return ClaudeAdapter.from_settings(settings)
        from app.inference.endpoint import EndpointAdapter

        return EndpointAdapter.from_settings(settings)
    raise ProviderUnavailableError(provider, "no production adapter exists for this provider")


def adapter_for(settings: Settings) -> DraftAdapter:
    key = _key(settings)
    with _lock:
        adapter = _adapters.get(key)
        if adapter is None:
            adapter = _build(settings)
            _adapters[key] = adapter
        return adapter


def peek_adapter(settings: Settings) -> DraftAdapter | None:
    """The cached adapter for these settings, if one was already built; never builds one."""
    with _lock:
        return _adapters.get(_key(settings))


def reset_adapters() -> None:
    """Drop cached adapters (tests, configuration reload). Local workers are shut down."""
    from app.inference.local import LocalTransformersAdapter

    with _lock:
        adapters = list(_adapters.values())
        _adapters.clear()
    for adapter in adapters:
        if isinstance(adapter, LocalTransformersAdapter):
            adapter.close()
