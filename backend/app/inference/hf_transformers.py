"""The production loader for :class:`LocalTransformersAdapter` (Hugging Face Transformers).

Importing this module imports neither ``torch`` nor ``transformers``; only
:func:`load_transformers_model` does, and the adapter calls it at most once per process, on
the first generation. Weights come from the local Hugging Face cache unless
``TUTOR_LOCAL_ALLOW_DOWNLOAD=true``. Decoding is greedy (no sampling), so the same prompt
gives the same draft on the same machine.
"""

import contextlib
import os
from collections.abc import Callable, Iterator
from typing import Any

from app.inference.errors import DeviceUnavailableError, ModelLoadError
from app.inference.local import GenerationOutput, LocalModel, LocalModelConfig
from app.inference.request import ProviderMessage

# Half precision is slow or unsupported for many CPU kernels, so it is not offered there.
_CPU_DTYPES = {"float32", "bfloat16"}


def _check_device(torch: Any, config: LocalModelConfig) -> None:
    device = config.device
    if device == "cpu":
        if config.dtype not in _CPU_DTYPES:
            raise DeviceUnavailableError(
                f"dtype {config.dtype} is not supported on cpu; use float32 or bfloat16"
            )
        return
    if device == "cuda" and not torch.cuda.is_available():
        raise DeviceUnavailableError("cuda was requested but no CUDA device is available")
    if device == "mps" and not torch.backends.mps.is_available():
        raise DeviceUnavailableError("mps was requested but the MPS backend is not available")
    if device not in {"cuda", "mps"}:
        raise DeviceUnavailableError(f"unknown device {device!r}")


class TransformersModel:
    """A loaded causal LM plus tokenizer, behind the adapter's :class:`LocalModel` protocol."""

    def __init__(self, torch: Any, model: Any, tokenizer: Any, device: str) -> None:
        self._torch = torch
        self._model = model
        self._tokenizer = tokenizer
        self._device = device

    def _prompt_ids(self, messages: list[ProviderMessage]) -> Any:
        rendered = self._tokenizer.apply_chat_template(
            [{"role": m.role, "content": m.content} for m in messages],
            tokenize=False,
            add_generation_prompt=True,
        )
        # The template already carries any special tokens; do not add a second set.
        return self._tokenizer(rendered, add_special_tokens=False, return_tensors="pt")

    def count_prompt_tokens(self, messages: list[ProviderMessage]) -> int:
        return int(self._prompt_ids(messages)["input_ids"].shape[-1])

    def generate(
        self,
        messages: list[ProviderMessage],
        *,
        max_new_tokens: int,
        should_stop: Callable[[], bool],
        on_text: Callable[[str], None],
    ) -> GenerationOutput:
        from transformers import StoppingCriteria, StoppingCriteriaList
        from transformers.generation.streamers import BaseStreamer

        torch = self._torch
        tokenizer = self._tokenizer
        encoded = self._prompt_ids(messages).to(self._device)
        generated: list[int] = []

        class _Stop(StoppingCriteria):
            def __call__(self, input_ids: Any, scores: Any = None, **kwargs: Any) -> Any:
                return torch.full(
                    (input_ids.shape[0],), should_stop(), dtype=torch.bool, device=input_ids.device
                )

        class _Stream(BaseStreamer):
            """Decodes the whole generated tail each step so multibyte tokens stay intact."""

            def __init__(self) -> None:
                self.emitted = 0
                self.skipped_prompt = False

            def put(self, value: Any) -> None:
                if not self.skipped_prompt:
                    self.skipped_prompt = True
                    return
                generated.extend(int(t) for t in value.reshape(-1).tolist())
                text = tokenizer.decode(generated, skip_special_tokens=True)
                if text.endswith("\ufffd"):
                    return
                if len(text) > self.emitted:
                    on_text(text[self.emitted :])
                    self.emitted = len(text)

            def end(self) -> None:
                return None

        eos = tokenizer.eos_token_id
        pad = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else eos
        with torch.inference_mode():
            self._model.generate(
                **encoded,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                stopping_criteria=StoppingCriteriaList([_Stop()]),
                streamer=_Stream(),
                pad_token_id=pad,
            )
        text = tokenizer.decode(generated, skip_special_tokens=True)
        ended = bool(generated) and eos is not None and generated[-1] == eos
        return GenerationOutput(
            text=text,
            output_tokens=len(generated),
            hit_length_limit=len(generated) >= max_new_tokens and not ended,
        )


@contextlib.contextmanager
def _hub_offline(enabled: bool) -> Iterator[None]:
    """Forbid every Hub request while loading from the local cache.

    ``local_files_only`` stops file downloads, but huggingface_hub still makes an unrelated
    request (agent-harness registry lookup while building request headers) unless its offline
    switch is on. The switch is read from a module constant after import, so the environment
    variable alone is not enough once the library has been imported.
    """
    if not enabled:
        yield
        return
    from huggingface_hub import constants

    previous_env = os.environ.get("HF_HUB_OFFLINE")
    previous_flag = constants.HF_HUB_OFFLINE
    os.environ["HF_HUB_OFFLINE"] = "1"
    constants.HF_HUB_OFFLINE = True
    try:
        yield
    finally:
        constants.HF_HUB_OFFLINE = previous_flag
        if previous_env is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = previous_env


def load_transformers_model(config: LocalModelConfig) -> LocalModel:
    """Load tokenizer and weights for ``config``; raises typed errors, never downloads silently."""
    try:
        import torch
        import transformers
    except ImportError as error:  # pragma: no cover - depends on the environment
        raise ModelLoadError(f"torch/transformers are not installed ({error.name})") from None

    _check_device(torch, config)
    dtype = getattr(torch, config.dtype)
    local_only = not config.allow_download
    common: dict[str, Any] = {
        "revision": config.revision,
        "local_files_only": local_only,
        "trust_remote_code": False,
    }
    try:
        with _hub_offline(local_only):
            tokenizer = transformers.AutoTokenizer.from_pretrained(config.model_id, **common)
            if not getattr(tokenizer, "chat_template", None):
                raise ModelLoadError("the tokenizer defines no chat template")
            model: Any = transformers.AutoModelForCausalLM.from_pretrained(
                config.model_id, dtype=dtype, **common
            )
        model.to(config.device)
        model.eval()
    except ModelLoadError:
        raise
    except Exception as error:
        hint = (
            "weights are read from the local cache only; set TUTOR_LOCAL_ALLOW_DOWNLOAD=true "
            "to permit a download"
            if local_only
            else "download was permitted"
        )
        raise ModelLoadError(
            f"could not load {config.model_id} ({type(error).__name__}); {hint}"
        ) from None
    return TransformersModel(torch, model, tokenizer, config.device)
