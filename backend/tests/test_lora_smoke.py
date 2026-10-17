"""Tiny random-base PEFT LoRA: real optimizer steps, frozen base, reload and comparison.

The base model is initialized from a small Llama config. Nothing here downloads weights, and a
passing run is not a claim that the adapter became a useful tutor.
"""

import os

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import pytest
import torch

from experiments.lora.model import (
    RELOAD_ATOL,
    PretrainedLoRADisabledError,
    UnsupportedLoRAConfigurationError,
    apply_lora,
    build_random_base,
)
from experiments.lora.rubric import compare_runs
from experiments.lora.train import evaluate_lora, train_smoke
from experiments.tutor_data.contracts import SharedExample

PROMPTS = (
    "Learner wrote 2x+3=14 for 2(x+3)=14. Ask about both terms. Do not state x=4.",
    "Learner solved x+5=9. Ask them to check the inverse step. Do not state x=4.",
)


def _example(example_id: str, family: str, prompt: str, completion: str) -> SharedExample:
    return SharedExample(
        example_id=example_id,
        source="rubberducky.fictional_shared.v1",
        terms="Fictional shared examples written for offline experiments. Not student work.",
        license="CC0-1.0",
        review_status="reviewed",
        reviewer="fixture-review",
        scenario_family=f"scenario.{family}",
        problem_family=f"problem.{family}",
        concept_family=f"concept.{family}",
        prompt=prompt,
        completion=completion,
        provenance="fictional_shared",
        forbidden_disclosure="x=4",
    )


def _examples() -> list[SharedExample]:
    return [
        _example("ex.train.1", "train", PROMPTS[0], "What should the 2 do to the 3 as well?"),
        _example("ex.train.2", "trainb", PROMPTS[1], "Which operation undoes adding 5?"),
        _example(
            "ex.held.1",
            "held",
            "Learner wrote 3y+1=15 for 3(y+1)=15. Ask about both terms. Do not state y=14/3.",
            "What should happen to the 1 when you multiply by 3?",
        ),
    ]


def test_unsupported_targets_and_pretrained_path_fail_before_download() -> None:
    base = build_random_base(seed=3)
    with pytest.raises(UnsupportedLoRAConfigurationError):
        apply_lora(base, target_modules=("not_a_real_module",), r=2, lora_alpha=4)
    calls: list[str] = []

    def _loader(model_id: str, revision: str) -> torch.nn.Module:
        calls.append(model_id + "@" + revision)
        raise AssertionError("pretrained loader must not run")

    try:
        build_random_base(seed=3, pretrained=True, allow_download=False, loader=_loader)
    except PretrainedLoRADisabledError:
        pass
    else:
        raise AssertionError("pretrained LoRA must stay disabled without an explicit download")
    assert calls == []


def test_lora_step_updates_adapter_only_and_reload_matches(tmp_path) -> None:
    examples = _examples()
    report = train_smoke(
        tmp_path / "lora",
        examples[:2],
        seed=17,
        steps=2,
        learning_rate=1e-2,
        target_modules=("q_proj", "v_proj"),
    )
    assert report["execution_status"] == "executed"
    assert report["loss_finite"] is True
    assert all(math_finite(value) for value in report["losses"])
    assert report["adapter_l1_delta"] > 0
    assert report["base_parameters_frozen"] is True
    assert report["base_max_abs_delta"] == 0.0
    assert report["threads"] <= 2
    assert report["pretrained_activated"] is False
    assert "q_proj" in report["target_modules"]
    labels = report["label_audit"]
    assert labels["prompt_and_pad_are_ignored"] is True
    assert -100 in labels["observed_ignore_index"]
    reload_report = report["reload"]
    assert reload_report["matched"] is True
    assert reload_report["max_abs_logit_diff"] <= RELOAD_ATOL
    card = (tmp_path / "lora" / "model-card.md").read_text()
    assert "random" in card.lower()
    assert "not a tuned tutor" in card.lower()
    evaluation = evaluate_lora(tmp_path / "lora", examples[2:])
    assert evaluation["decoding"] == report["decoding"]
    assert evaluation["base"]["example_ids"] == ["ex.held.1"]
    assert evaluation["adapter"]["example_ids"] == ["ex.held.1"]
    assert "improvements" in evaluation and "regressions" in evaluation
    assert evaluation["limitations"]
    with pytest.raises(UnsupportedLoRAConfigurationError):
        train_smoke(
            tmp_path / "bad",
            examples,
            seed=1,
            steps=1,
            target_modules=("c_attn",),
        )


def math_finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


def test_comparison_reports_regressions_as_well_as_improvements() -> None:
    base = {"ex.1": {"answer_withheld": 1.0, "completion_nll": 2.0}}
    adapter = {"ex.1": {"answer_withheld": 0.0, "completion_nll": 1.0}}
    report = compare_runs(
        base,
        adapter,
        higher_is_better=("answer_withheld",),
        lower_is_better=("completion_nll",),
    )
    assert any(item["metric"] == "answer_withheld" for item in report["regressions"])
    assert any(item["metric"] == "completion_nll" for item in report["improvements"])
