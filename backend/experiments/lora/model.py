"""Tiny random Llama plus PEFT LoRA. The pretrained path is opt-in and not activated."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import torch
from torch import nn

from experiments.threads import limit_numerical_threads

PRETRAINED_MODEL_ID = "HuggingFaceTB/SmolLM2-135M-Instruct"
PRETRAINED_REVISION = "12fd25f77366fa6b3b4b768ec3050bf629380bac"
RELOAD_ATOL = 1e-4


class UnsupportedLoRAConfigurationError(ValueError):
    """The requested LoRA targets are not linear modules of this architecture."""


class PretrainedLoRADisabledError(RuntimeError):
    """A pretrained base was requested without an explicit, still-inactive download."""


@dataclass(frozen=True)
class TinyLlamaSpec:
    vocab_size: int = 64
    hidden_size: int = 32
    intermediate_size: int = 64
    num_hidden_layers: int = 1
    num_attention_heads: int = 4
    num_key_value_heads: int = 2
    max_position_embeddings: int = 256

    def to_json(self) -> dict[str, int]:
        return {
            "vocab_size": self.vocab_size,
            "hidden_size": self.hidden_size,
            "intermediate_size": self.intermediate_size,
            "num_hidden_layers": self.num_hidden_layers,
            "num_attention_heads": self.num_attention_heads,
            "num_key_value_heads": self.num_key_value_heads,
            "max_position_embeddings": self.max_position_embeddings,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "TinyLlamaSpec":
        values: dict[str, int] = {}
        for name in (
            "vocab_size",
            "hidden_size",
            "intermediate_size",
            "num_hidden_layers",
            "num_attention_heads",
            "num_key_value_heads",
            "max_position_embeddings",
        ):
            raw = payload[name]
            if not isinstance(raw, int):
                raise TypeError(f"{name} must be an int")
            values[name] = raw
        return cls(**values)


def build_random_base(
    *,
    seed: int,
    spec: TinyLlamaSpec | None = None,
    pretrained: bool = False,
    allow_download: bool = False,
    loader: Callable[[str, str], nn.Module] | None = None,
) -> nn.Module:
    """Build a causal LM. The default is a randomly initialized tiny Llama, offline.

    ``pretrained=True`` does not download. Without ``allow_download`` it refuses. With the
    flag it still refuses unless the caller passes a loader, and this repository's commands
    do not pass one.
    """

    if pretrained:
        if not allow_download:
            raise PretrainedLoRADisabledError(
                "pretrained LoRA is opt-in and weight download is not enabled"
            )
        if loader is None:
            raise PretrainedLoRADisabledError(
                "pretrained download is configured but not activated in this command"
            )
        return loader(PRETRAINED_MODEL_ID, PRETRAINED_REVISION)
    limit_numerical_threads(2)
    torch.manual_seed(seed)
    spec = spec or TinyLlamaSpec()
    from transformers import LlamaConfig, LlamaForCausalLM

    config = LlamaConfig(
        vocab_size=spec.vocab_size,
        hidden_size=spec.hidden_size,
        intermediate_size=spec.intermediate_size,
        num_hidden_layers=spec.num_hidden_layers,
        num_attention_heads=spec.num_attention_heads,
        num_key_value_heads=spec.num_key_value_heads,
        max_position_embeddings=spec.max_position_embeddings,
        rms_norm_eps=1e-5,
        pad_token_id=0,
        bos_token_id=1,
        eos_token_id=2,
        tie_word_embeddings=True,
    )
    return LlamaForCausalLM(config)  # type: ignore[no-untyped-call]


def linear_module_names(model: nn.Module) -> set[str]:
    names: set[str] = set()
    for module_name, module in model.named_modules():
        if isinstance(module, nn.Linear):
            names.add(module_name.split(".")[-1])
    return names


def apply_lora(
    model: nn.Module,
    *,
    target_modules: Sequence[str],
    r: int = 2,
    lora_alpha: int = 4,
) -> nn.Module:
    """Attach a causal-LM LoRA adapter. Unknown module names raise before PEFT mutates."""

    if r < 1 or lora_alpha < 1:
        raise UnsupportedLoRAConfigurationError("LoRA rank and alpha must be positive")
    if not target_modules:
        raise UnsupportedLoRAConfigurationError(
            "target_modules must name at least one linear module"
        )
    available = linear_module_names(model)
    missing = sorted(set(target_modules) - available)
    if missing:
        available_list = ", ".join(sorted(available)) or "(none)"
        raise UnsupportedLoRAConfigurationError(
            f"unsupported target modules {missing}; available linear modules: {available_list}"
        )
    from peft import LoraConfig, TaskType, get_peft_model

    config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=r,
        lora_alpha=lora_alpha,
        lora_dropout=0.0,
        bias="none",
        target_modules=list(target_modules),
    )
    return get_peft_model(model, config)
