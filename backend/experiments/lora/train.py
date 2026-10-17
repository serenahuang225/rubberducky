"""Tiny random-base LoRA smoke: real backward steps, frozen base, reload and comparison.

This is pipeline verification. A lower held-out loss is not evidence of a useful tutor, and
the base weights are random rather than a pretrained checkpoint.
"""

import json
import resource
import time
from pathlib import Path
from typing import Any, cast

import torch

from experiments.lora.model import (
    RELOAD_ATOL,
    TinyLlamaSpec,
    apply_lora,
    build_random_base,
)
from experiments.lora.rubric import compare_runs, score_completion
from experiments.threads import limit_numerical_threads
from experiments.tutor_data.contracts import SharedExample
from experiments.tutor_data.masks import completion_only_labels, encode_pair, encode_text

DECODING: dict[str, object] = {
    "do_sample": False,
    "max_new_tokens": 8,
    "temperature": None,
    "num_beams": 1,
}
LIMITATION = (
    "Randomly initialized tiny Transformer and a few CPU steps on fictional examples. "
    "Not a tuned tutor, not a pretrained-model run, and not an educational improvement."
)


def train_smoke(
    output: Path,
    examples: list[SharedExample],
    *,
    seed: int,
    steps: int,
    learning_rate: float = 1e-2,
    target_modules: tuple[str, ...] = ("q_proj", "v_proj"),
    threads: int = 2,
) -> dict[str, object]:
    if steps < 1:
        raise ValueError("steps must be positive")
    if any(example.review_status != "reviewed" for example in examples):
        raise ValueError("training refuses unreviewed examples")
    applied = limit_numerical_threads(threads)
    started = time.perf_counter()
    spec = TinyLlamaSpec()
    base = build_random_base(seed=seed, spec=spec, pretrained=False, allow_download=False)
    base_state = {name: tensor.detach().cpu().clone() for name, tensor in base.state_dict().items()}
    peft_model = apply_lora(base, target_modules=target_modules, r=2, lora_alpha=4)
    named = list(peft_model.named_parameters())
    trainable = [(name, param) for name, param in named if param.requires_grad]
    frozen = [(name, param) for name, param in named if not param.requires_grad]
    if not trainable:
        raise RuntimeError("LoRA added no trainable parameters")
    if any("lora_" not in name for name, _param in trainable):
        raise RuntimeError("a non-adapter parameter was left trainable")
    frozen_before = {name: param.detach().clone() for name, param in frozen}
    adapter_before = {name: param.detach().clone() for name, param in trainable}
    optimizer = torch.optim.AdamW([param for _name, param in trainable], lr=learning_rate)
    input_ids, labels = _supervised_batch(examples, spec)
    audit = _label_audit(examples, spec, input_ids, labels)
    peft_model.train()
    losses: list[float] = []
    for _step in range(steps):
        optimizer.zero_grad()
        loss = peft_model(input_ids=input_ids, labels=labels, use_cache=False).loss
        if not torch.isfinite(loss):
            raise RuntimeError("LoRA loss was not finite")
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach()))
    base_delta = 0.0
    for name, param in peft_model.named_parameters():
        if name in frozen_before:
            base_delta = max(base_delta, float((param.detach() - frozen_before[name]).abs().max()))
    adapter_delta = 0.0
    for name, param in peft_model.named_parameters():
        if name in adapter_before:
            adapter_delta += float((param.detach() - adapter_before[name]).abs().sum())
    output.mkdir(parents=True, exist_ok=True)
    torch.save(base_state, output / "base_state.pt")
    adapter_dir = output / "adapter"
    cast(Any, peft_model).save_pretrained(adapter_dir)
    config = {
        "seed": seed,
        "steps": steps,
        "learning_rate": learning_rate,
        "target_modules": list(target_modules),
        "r": 2,
        "lora_alpha": 4,
        "pretrained": False,
        "allow_download": False,
        "model_id": None,
        "revision": None,
        "spec": spec.to_json(),
        "decoding": DECODING,
        "reload_atol": RELOAD_ATOL,
        "threads": applied,
    }
    (output / "config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    peft_model.eval()
    reload_diff = _reload_logit_diff(output, peft_model, input_ids)
    (output / "probe.json").write_text(json.dumps({"input_ids": input_ids.tolist()}) + "\n")
    elapsed = time.perf_counter() - started
    report: dict[str, object] = {
        "execution_status": "executed",
        "seed": seed,
        "steps": steps,
        "loss_finite": all(_finite(value) for value in losses),
        "losses": losses,
        "adapter_l1_delta": adapter_delta,
        "base_parameters_frozen": base_delta == 0.0,
        "base_max_abs_delta": base_delta,
        "threads": applied,
        "pretrained_activated": False,
        "target_modules": list(target_modules),
        "label_audit": audit,
        "decoding": dict(DECODING),
        "reload": {
            "max_abs_logit_diff": reload_diff,
            "atol": RELOAD_ATOL,
            "matched": reload_diff <= RELOAD_ATOL,
        },
        "elapsed_seconds": elapsed,
        "max_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "limitations": LIMITATION,
    }
    (output / "metrics.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (output / "model-card.md").write_text(_card(report))
    return report


def reload_checkpoint(checkpoint: Path) -> dict[str, object]:
    """Load the adapter onto the saved random base and compare logits to a fresh load."""

    limit_numerical_threads(2)
    probe = json.loads((checkpoint / "probe.json").read_text())
    input_ids = torch.tensor(probe["input_ids"], dtype=torch.long)
    first = _load_peft(checkpoint)
    second = _load_peft(checkpoint)
    first.eval()
    second.eval()
    with torch.no_grad():
        left = first(input_ids=input_ids).logits
        right = second(input_ids=input_ids).logits
    diff = float((left - right).abs().max())
    return {
        "max_abs_logit_diff": diff,
        "atol": RELOAD_ATOL,
        "matched": diff <= RELOAD_ATOL,
        "pretrained_activated": False,
    }


def evaluate_lora(checkpoint: Path, examples: list[SharedExample]) -> dict[str, object]:
    """Score the saved base and the adapter on the same prompts, decoding and rubric."""

    limit_numerical_threads(2)
    config = json.loads((checkpoint / "config.json").read_text())
    decoding = config["decoding"]
    if not isinstance(decoding, dict):
        raise TypeError("checkpoint decoding settings are missing")
    spec = TinyLlamaSpec.from_json(config["spec"])
    base = _load_base(checkpoint, spec)
    adapter = _load_peft(checkpoint)
    base.eval()
    adapter.eval()
    max_new = int(decoding["max_new_tokens"])
    base_scores: dict[str, dict[str, float]] = {}
    adapter_scores: dict[str, dict[str, float]] = {}
    texts: dict[str, dict[str, str]] = {}
    for example in examples:
        prompt_ids = _prompt_ids(example.prompt, spec, max_new)
        base_text = _generate(base, prompt_ids, max_new)
        adapter_text = _generate(adapter, prompt_ids, max_new)
        base_scores[example.example_id] = score_completion(
            example, base_text, completion_nll=_nll(base, example, spec)
        )
        adapter_scores[example.example_id] = score_completion(
            example, adapter_text, completion_nll=_nll(adapter, example, spec)
        )
        texts[example.example_id] = {"base": base_text, "adapter": adapter_text}
    comparison = compare_runs(base_scores, adapter_scores)
    return {
        "decoding": decoding,
        "base": {
            "example_ids": [example.example_id for example in examples],
            "scores": base_scores,
        },
        "adapter": {
            "example_ids": [example.example_id for example in examples],
            "scores": adapter_scores,
        },
        "completions": texts,
        "improvements": comparison["improvements"],
        "regressions": comparison["regressions"],
        "limitations": LIMITATION,
        "pretrained_activated": False,
    }


def _supervised_batch(
    examples: list[SharedExample], spec: TinyLlamaSpec
) -> tuple[torch.Tensor, torch.Tensor]:
    encoded = [
        encode_pair(example.prompt, example.completion, vocab_size=spec.vocab_size)
        for example in examples
    ]
    width = min(spec.max_position_embeddings, max(len(item.token_ids) for item in encoded))
    rows: list[list[int]] = []
    label_rows: list[list[int]] = []
    for item in encoded:
        ids = item.token_ids[:width]
        prompt_len = min(item.prompt_len, len(ids))
        labels = completion_only_labels(ids, prompt_len, pad_id=item.pad_id)
        pad = width - len(ids)
        rows.append(ids + [item.pad_id] * pad)
        label_rows.append(labels + [-100] * pad)
    return torch.tensor(rows, dtype=torch.long), torch.tensor(label_rows, dtype=torch.long)


def _label_audit(
    examples: list[SharedExample],
    spec: TinyLlamaSpec,
    input_ids: torch.Tensor,
    labels: torch.Tensor,
) -> dict[str, object]:
    ignored = True
    for row, example in enumerate(examples):
        encoded = encode_pair(example.prompt, example.completion, vocab_size=spec.vocab_size)
        prompt_len = min(encoded.prompt_len, input_ids.shape[1])
        if any(int(labels[row, index]) != -100 for index in range(prompt_len)):
            ignored = False
        for index, token in enumerate(input_ids[row].tolist()):
            if int(token) == 0 and int(labels[row, index]) != -100:
                ignored = False
    observed = sorted({int(value) for value in labels.reshape(-1).tolist() if int(value) < 0})
    return {"prompt_and_pad_are_ignored": ignored, "observed_ignore_index": observed}


def _reload_logit_diff(
    checkpoint: Path, trained: torch.nn.Module, input_ids: torch.Tensor
) -> float:
    reloaded = _load_peft(checkpoint)
    reloaded.eval()
    trained.eval()
    with torch.no_grad():
        left = trained(input_ids=input_ids).logits
        right = reloaded(input_ids=input_ids).logits
    return float((left - right).abs().max())


def _load_base(checkpoint: Path, spec: TinyLlamaSpec) -> torch.nn.Module:
    # The seed only selects the architecture. Weights come from the saved random base.
    model = build_random_base(seed=0, spec=spec, pretrained=False, allow_download=False)
    state = torch.load(checkpoint / "base_state.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(state)
    return model


def _load_peft(checkpoint: Path) -> torch.nn.Module:
    from peft import PeftModel

    config = json.loads((checkpoint / "config.json").read_text())
    spec = TinyLlamaSpec.from_json(config["spec"])
    base = _load_base(checkpoint, spec)
    return PeftModel.from_pretrained(base, checkpoint / "adapter")


def _prompt_ids(prompt: str, spec: TinyLlamaSpec, max_new_tokens: int) -> torch.Tensor:
    room = max(1, spec.max_position_embeddings - max_new_tokens)
    ids = encode_text(prompt, vocab_size=spec.vocab_size)[:room]
    return torch.tensor([ids], dtype=torch.long)


def _generate(model: torch.nn.Module, prompt_ids: torch.Tensor, max_new_tokens: int) -> str:
    attention = torch.ones_like(prompt_ids)
    with torch.no_grad():
        generated = cast(Any, model).generate(
            input_ids=prompt_ids,
            attention_mask=attention,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=0,
        )
    new_tokens = generated[0, prompt_ids.shape[1] :].tolist()
    return " ".join(str(token) for token in new_tokens)


def _nll(model: torch.nn.Module, example: SharedExample, spec: TinyLlamaSpec) -> float:
    input_ids, labels = _supervised_batch([example], spec)
    with torch.no_grad():
        loss = model(input_ids=input_ids, labels=labels, use_cache=False).loss
    if not torch.isfinite(loss):
        raise RuntimeError("evaluation NLL was not finite")
    return float(loss)


def _card(report: dict[str, object]) -> str:
    reload = report["reload"]
    if not isinstance(reload, dict):
        raise TypeError("reload report missing")
    return "\n".join(
        [
            "# LoRA random-base smoke model card",
            "",
            "This artifact is a **random**-base LoRA plumbing check. It is **not a tuned tutor**,",
            "not a pretrained-model run, and not evidence of better teaching.",
            "",
            f"- Seed: `{report.get('seed')}`. Steps: `{report.get('steps')}`.",
            f"- Threads: {report['threads']}.",
            f"- Pretrained path activated: `{report['pretrained_activated']}`.",
            f"- Target modules: `{report['target_modules']}`.",
            f"- Adapter L1 change: {report['adapter_l1_delta']}.",
            f"- Base max absolute change: {report['base_max_abs_delta']} (frozen expected).",
            f"- Reload max absolute logit difference: {reload['max_abs_logit_diff']} "
            f"(tolerance {reload['atol']}).",
            f"- Elapsed seconds: {report['elapsed_seconds']}.",
            f"- Max RSS bytes: {report['max_rss_bytes']}.",
            "",
            "## Limitations",
            "",
            LIMITATION,
            "Base and adapter use the same held-out prompts, greedy decoding and rubric,",
            "and regressions are reported beside improvements.",
            "",
        ]
    )


def _finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))
