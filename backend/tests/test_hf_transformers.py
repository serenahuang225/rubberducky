"""The production Hugging Face loader and generator, with no weights downloaded.

``load_transformers_model`` runs for real with ``from_pretrained`` replaced by recorders (so
the exact keyword arguments are observed), and with a real offline miss. ``TransformersModel``
runs real ``torch`` / ``transformers`` generation on a tiny *randomly initialised* Llama with a
byte-level stand-in tokenizer. That proves streaming, stop-polling, length-limit and token
accounting of our code; it says nothing about pretrained SmolLM2 quality or latency.
"""

import os
import threading
from typing import Any

import pytest
import torch
import transformers
from huggingface_hub import constants as hub_constants
from transformers import BatchEncoding, LlamaConfig, LlamaForCausalLM

from app.inference.errors import DeviceUnavailableError, ModelLoadError
from app.inference.hf_transformers import TransformersModel, load_transformers_model
from app.inference.local import LocalModelConfig
from app.inference.request import ProviderMessage

torch.set_num_threads(2)

EOS = 257
VOCAB = 260


class ByteTokenizer:
    """UTF-8 bytes as ids; ids >= 256 are special and decode to nothing."""

    chat_template = "stand-in"
    eos_token_id = EOS
    pad_token_id = None

    def apply_chat_template(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        assert kwargs == {"tokenize": False, "add_generation_prompt": True}
        return "".join(f"<{m['role']}>{m['content']}" for m in messages) + "<assistant>"

    def __call__(self, text: str, *, add_special_tokens: bool, return_tensors: str) -> Any:
        assert add_special_tokens is False and return_tensors == "pt"
        ids = torch.tensor([list(text.encode("utf-8"))], dtype=torch.long)
        return BatchEncoding({"input_ids": ids, "attention_mask": torch.ones_like(ids)})

    def decode(self, ids: list[int], skip_special_tokens: bool = True) -> str:
        data = bytes(i for i in ids if i < 256)
        return data.decode("utf-8", errors="replace")


@pytest.fixture(scope="module")
def tiny_model() -> Any:
    torch.manual_seed(7)
    model = LlamaForCausalLM(
        LlamaConfig(
            vocab_size=VOCAB,
            hidden_size=16,
            intermediate_size=32,
            num_hidden_layers=1,
            num_attention_heads=2,
            num_key_value_heads=2,
            max_position_embeddings=512,
            eos_token_id=EOS,
            bos_token_id=256,
        )
    )
    model.eval()
    return model


def messages(text: str = "hello") -> list[ProviderMessage]:
    return [
        ProviderMessage(role="system", content="You are a tutor."),
        ProviderMessage(role="user", content=text),
    ]


def make_config(**overrides: object) -> LocalModelConfig:
    values: dict[str, object] = {
        "model_id": "HuggingFaceTB/SmolLM2-135M-Instruct",
        "revision": "12fd25f77366fa6b3b4b768ec3050bf629380bac",
        "device": "cpu",
        "dtype": "float32",
        "allow_download": False,
        "context_window_tokens": 4096,
        "max_new_tokens": 16,
        "max_queue": 0,
        "timeout_seconds": 30.0,
    }
    values.update(overrides)
    return LocalModelConfig(**values)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _blocked(no_network: list) -> list:
    return no_network


class TestRealGeneration:
    def test_prompt_token_count_matches_the_templated_prompt(self, tiny_model: Any) -> None:
        model = TransformersModel(torch, tiny_model, ByteTokenizer(), "cpu")
        rendered = ByteTokenizer().apply_chat_template(
            [{"role": m.role, "content": m.content} for m in messages()],
            tokenize=False,
            add_generation_prompt=True,
        )
        assert model.count_prompt_tokens(messages()) == len(rendered.encode("utf-8"))

    def test_greedy_generation_streams_exactly_the_final_text_and_is_deterministic(
        self, tiny_model: Any
    ) -> None:
        model = TransformersModel(torch, tiny_model, ByteTokenizer(), "cpu")
        runs = []
        for _ in range(2):
            fragments: list[str] = []
            output = model.generate(
                messages(), max_new_tokens=12, should_stop=lambda: False, on_text=fragments.append
            )
            assert "".join(fragments) == output.text
            assert 1 <= output.output_tokens <= 12
            runs.append((output.text, output.output_tokens, output.hit_length_limit))
        assert runs[0] == runs[1]

    def test_reaching_the_new_token_ceiling_is_reported_as_a_length_stop(
        self, tiny_model: Any
    ) -> None:
        model = TransformersModel(torch, tiny_model, ByteTokenizer(), "cpu")
        output = model.generate(
            messages(), max_new_tokens=5, should_stop=lambda: False, on_text=lambda _t: None
        )
        # A random model has no reason to emit the end token within five steps.
        assert output.output_tokens == 5
        assert output.hit_length_limit is True

    def test_stop_signal_halts_real_generation_between_tokens(self, tiny_model: Any) -> None:
        model = TransformersModel(torch, tiny_model, ByteTokenizer(), "cpu")
        polls = 0

        def should_stop() -> bool:
            nonlocal polls
            polls += 1
            return polls > 3

        output = model.generate(
            messages(), max_new_tokens=64, should_stop=should_stop, on_text=lambda _t: None
        )
        assert output.output_tokens < 64
        assert output.hit_length_limit is False

    def test_a_stop_set_before_generation_yields_at_most_one_token(self, tiny_model: Any) -> None:
        model = TransformersModel(torch, tiny_model, ByteTokenizer(), "cpu")
        output = model.generate(
            messages(), max_new_tokens=64, should_stop=lambda: True, on_text=lambda _t: None
        )
        assert output.output_tokens <= 1


class TestLoaderArguments:
    @pytest.fixture
    def recorded(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        seen: dict[str, Any] = {"calls": []}

        class Tok(ByteTokenizer):
            pass

        def tokenizer_from_pretrained(model_id: str, **kwargs: Any) -> Any:
            seen["calls"].append(("tokenizer", model_id, kwargs))
            seen.setdefault("hub_offline", []).append(hub_constants.HF_HUB_OFFLINE)
            tokenizer = Tok()
            if seen.get("no_template"):
                tokenizer.chat_template = None  # type: ignore[assignment]
            return tokenizer

        class Model:
            def to(self, device: str) -> "Model":
                seen["device"] = device
                return self

            def eval(self) -> "Model":
                seen["eval"] = True
                return self

        def model_from_pretrained(model_id: str, **kwargs: Any) -> Any:
            seen["calls"].append(("model", model_id, kwargs))
            if seen.get("fail"):
                raise OSError("/Users/someone/.cache/secret-path not found")
            return Model()

        monkeypatch.setattr(
            transformers.AutoTokenizer, "from_pretrained", tokenizer_from_pretrained
        )
        monkeypatch.setattr(
            transformers.AutoModelForCausalLM, "from_pretrained", model_from_pretrained
        )
        return seen

    def test_default_loads_the_pinned_revision_from_the_local_cache_only(
        self, recorded: dict[str, Any]
    ) -> None:
        loaded = load_transformers_model(make_config())
        assert isinstance(loaded, TransformersModel)
        (_, tok_id, tok_kwargs), (_, model_id, model_kwargs) = recorded["calls"]
        assert tok_id == model_id == "HuggingFaceTB/SmolLM2-135M-Instruct"
        for kwargs in (tok_kwargs, model_kwargs):
            assert kwargs["revision"] == "12fd25f77366fa6b3b4b768ec3050bf629380bac"
            assert kwargs["local_files_only"] is True
            assert kwargs["trust_remote_code"] is False
        assert model_kwargs["dtype"] is torch.float32
        assert recorded["device"] == "cpu" and recorded["eval"] is True

    def test_download_needs_the_explicit_opt_in(self, recorded: dict[str, Any]) -> None:
        load_transformers_model(make_config(allow_download=True, dtype="bfloat16"))
        for _, _, kwargs in recorded["calls"]:
            assert kwargs["local_files_only"] is False
        assert recorded["calls"][1][2]["dtype"] is torch.bfloat16

    def test_cache_only_loads_switch_the_hub_offline_and_restore_it_afterwards(
        self, recorded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hub_constants, "HF_HUB_OFFLINE", False)
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        load_transformers_model(make_config())
        assert recorded["hub_offline"] == [True]
        assert hub_constants.HF_HUB_OFFLINE is False
        assert "HF_HUB_OFFLINE" not in os.environ

    def test_opted_in_downloads_leave_the_hub_switch_alone(
        self, recorded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hub_constants, "HF_HUB_OFFLINE", False)
        load_transformers_model(make_config(allow_download=True))
        assert recorded["hub_offline"] == [False]

    def test_a_missing_chat_template_is_a_load_error(self, recorded: dict[str, Any]) -> None:
        recorded["no_template"] = True
        with pytest.raises(ModelLoadError, match="chat template"):
            load_transformers_model(make_config())

    def test_load_failures_name_the_exception_type_but_not_paths(
        self, recorded: dict[str, Any]
    ) -> None:
        recorded["fail"] = True
        with pytest.raises(ModelLoadError) as caught:
            load_transformers_model(make_config())
        assert "OSError" in str(caught.value)
        assert "/Users/someone" not in str(caught.value)
        assert "TUTOR_LOCAL_ALLOW_DOWNLOAD" in str(caught.value)

    def test_real_offline_miss_fails_typed_without_touching_the_network(
        self, no_network: list
    ) -> None:
        with pytest.raises(ModelLoadError) as caught:
            load_transformers_model(make_config(model_id="rubberducky-test/not-a-real-model"))
        assert "local cache only" in str(caught.value) or "TUTOR_LOCAL_ALLOW_DOWNLOAD" in str(
            caught.value
        )
        assert no_network == []


class TestDeviceAndDtype:
    def test_cpu_rejects_half_precision(self) -> None:
        with pytest.raises(DeviceUnavailableError, match="float16"):
            load_transformers_model(make_config(dtype="float16"))

    @pytest.mark.parametrize("dtype", ["float32", "bfloat16"])
    def test_cpu_accepts_float32_and_bfloat16(
        self, dtype: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reached = threading.Event()

        def stop(*_a: object, **_k: object) -> Any:
            reached.set()
            raise OSError("stop after device validation")

        monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", stop)
        with pytest.raises(ModelLoadError):
            load_transformers_model(make_config(dtype=dtype))
        assert reached.is_set()

    def test_cuda_without_a_device_is_reported_and_loads_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
        called = []
        monkeypatch.setattr(
            transformers.AutoTokenizer, "from_pretrained", lambda *a, **k: called.append(1)
        )
        with pytest.raises(DeviceUnavailableError, match="cuda"):
            load_transformers_model(make_config(device="cuda"))
        assert called == []

    def test_mps_without_the_backend_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
        with pytest.raises(DeviceUnavailableError, match="mps"):
            load_transformers_model(make_config(device="mps", dtype="float16"))

    def test_unknown_device_is_refused(self) -> None:
        with pytest.raises(DeviceUnavailableError, match="unknown device"):
            load_transformers_model(make_config(device="tpu"))
