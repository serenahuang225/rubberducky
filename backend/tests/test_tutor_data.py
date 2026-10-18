"""Shared-tutor preparation: provenance, review, family splits and completion masks."""

import ast
import json
from pathlib import Path

import pytest

from experiments.tutor_data.masks import completion_only_labels, encode_pair
from experiments.tutor_data.prepare import prepare_examples, validate_examples
from experiments.tutor_data.teacher import (
    TeacherBudgetError,
    TeacherGenerationDisabledError,
    generate_teacher_examples,
)

FIXTURE = (
    Path(__file__).parents[1]
    / "experiments"
    / "tutor_data"
    / "fixtures"
    / "reviewed_shared.jsonl"
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "example_id": "ex.grouping.1",
        "source": "rubberducky.fictional_shared.v1",
        "terms": "Fictional shared examples written for offline experiments. Not student work.",
        "license": "CC0-1.0",
        "review_status": "reviewed",
        "reviewer": "fixture-review",
        "scenario_family": "scenario.grouping",
        "problem_family": "problem.two_x_plus_3",
        "concept_family": "concept.distribution",
        "prompt": "Learner wrote 2x+3=14 for 2(x+3)=14. Ask about both terms. Do not state x=4.",
        "completion": "You multiplied the 2 by x. What should happen to the 3 as well?",
        "private": False,
        "provenance": "fictional_shared",
        "forbidden_disclosure": "x=4",
    }
    row.update(overrides)
    return row


def _family(suffix: str, *, scenario: str) -> dict[str, object]:
    return _row(
        example_id=f"ex.{suffix}",
        scenario_family=scenario,
        problem_family=f"problem.{suffix}",
        concept_family=f"concept.{suffix}",
        prompt=f"Prompt for {suffix}. Do not give the final value.",
        completion=f"Question about {suffix} only.",
    )


class _Transport:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "What happens to both terms?"


def test_completion_mask_drops_prompt_and_padding() -> None:
    encoded = encode_pair("Ask about both terms.", "What about the 3?", vocab_size=64)
    labels = completion_only_labels(
        encoded.token_ids, encoded.prompt_len, pad_id=encoded.pad_id
    )
    assert len(labels) == len(encoded.token_ids)
    assert labels[: encoded.prompt_len] == [-100] * encoded.prompt_len
    completion = encoded.token_ids[encoded.prompt_len :]
    assert labels[encoded.prompt_len :] == completion
    padded = [*encoded.token_ids, encoded.pad_id, encoded.pad_id]
    padded_labels = completion_only_labels(padded, encoded.prompt_len, pad_id=encoded.pad_id)
    assert padded_labels[-2:] == [-100, -100]
    assert any(label != -100 for label in padded_labels)


def test_prepare_keeps_reviewed_families_together_and_rejects_bad_rows() -> None:
    records = [
        _family("alpha", scenario="scenario.alpha"),
        _family("beta", scenario="scenario.beta"),
        _row(
            example_id="ex.unreviewed",
            scenario_family="scenario.gamma",
            problem_family="problem.gamma",
            concept_family="concept.gamma",
            review_status="unreviewed",
            reviewer=None,
        ),
        _row(example_id="ex.private", private=True, provenance="learner_recording"),
        _row(example_id="ex.nosource", source=""),
        _row(example_id="ex.learner", learner_id="learner.ada"),
        _row(
            example_id="ex.public",
            provenance="public_dataset",
            scenario_family="scenario.public",
            problem_family="problem.public",
            concept_family="concept.public",
        ),
        _row(
            example_id="ex.leak.train",
            scenario_family="scenario.leak",
            problem_family="problem.leak",
            concept_family="concept.leak",
            declared_split="train",
        ),
        _row(
            example_id="ex.leak.held",
            scenario_family="scenario.leak",
            problem_family="problem.leak",
            concept_family="concept.leak",
            prompt="Related leak prompt.",
            completion="Related leak question?",
            declared_split="held_out",
        ),
        {"example_id": "ex.bad", "prompt": "missing everything else"},
    ]
    prepared = prepare_examples(records, seed=17, heldout_fraction=0.5)
    train_ids = set(prepared.train_ids)
    heldout_ids = set(prepared.heldout_ids)
    assert train_ids.isdisjoint(heldout_ids)
    assert train_ids | heldout_ids <= {"ex.alpha", "ex.beta"}
    reasons = {item.example_id: item.reason for item in prepared.excluded}
    assert reasons["ex.unreviewed"] == "unreviewed"
    assert "private" in reasons["ex.private"]
    assert reasons["ex.nosource"] == "missing_source"
    assert reasons["ex.learner"] == "per_learner_finetune"
    assert reasons["ex.public"] == "public_dataset_missing_documentation"
    assert reasons["ex.leak.train"] == "cross_split_family"
    assert reasons["ex.leak.held"] == "cross_split_family"
    assert reasons["ex.bad"] == "malformed"
    families = {prepared.family_by_id[example_id] for example_id in train_ids | heldout_ids}
    for family in families:
        members = [
            example_id
            for example_id, member_family in prepared.family_by_id.items()
            if member_family == family and example_id in train_ids | heldout_ids
        ]
        sides = {example_id in train_ids for example_id in members}
        assert len(sides) == 1


def test_shipped_fixture_validates_without_downloads(tmp_path: Path) -> None:
    report = validate_examples(FIXTURE)
    assert report.accepted_ids
    assert report.download_count == 0
    prepared = prepare_examples(
        FIXTURE, seed=17, heldout_fraction=0.34, output_dir=tmp_path
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert prepared.train_ids == manifest["train_ids"]
    assert manifest["train_ids"]
    assert manifest["heldout_ids"]
    assert set(manifest["train_ids"]).isdisjoint(manifest["heldout_ids"])
    train_text = (tmp_path / "train.jsonl").read_text()
    assert "learner_recording" not in train_text
    masks = json.loads((tmp_path / "masks.json").read_text())
    assert masks[0]["labels"][: masks[0]["prompt_len"]] == [-100] * masks[0]["prompt_len"]


def test_dry_run_writes_a_manifest_and_no_training_rows(tmp_path: Path) -> None:
    prepared = prepare_examples(
        [_family("alpha", scenario="scenario.alpha"), _family("beta", scenario="scenario.beta")],
        seed=4,
        heldout_fraction=0.5,
        output_dir=tmp_path,
        dry_run=True,
    )
    assert prepared.dry_run is True
    assert (tmp_path / "manifest.json").is_file()
    assert not (tmp_path / "train.jsonl").exists()
    assert not (tmp_path / "heldout.jsonl").exists()


def test_teacher_generation_is_disabled_until_activated_and_stays_unreviewed() -> None:
    transport = _Transport()
    prompts = ["Ask a question about 2(x+3)=14 without solving it."]
    with pytest.raises(TeacherGenerationDisabledError):
        generate_teacher_examples(prompts, transport=transport, activated=False, max_cost_usd=1)
    assert transport.prompts == []

    with pytest.raises(TeacherBudgetError):
        generate_teacher_examples(
            prompts, transport=transport, activated=True, max_cost_usd=0, provider="mock"
        )
    assert transport.prompts == []

    with pytest.raises(TeacherGenerationDisabledError):
        generate_teacher_examples(
            prompts,
            transport=transport,
            activated=True,
            max_cost_usd=1,
            provider="claude",
            allow_remote=False,
        )
    assert transport.prompts == []

    generated = generate_teacher_examples(
        prompts,
        transport=transport,
        activated=True,
        max_cost_usd=0.5,
        provider="mock",
        model_id="mock-teacher",
        model_version="mock.v1",
    )
    assert transport.prompts == prompts
    assert generated[0].review_status == "unreviewed"
    assert generated[0].provenance == "teacher_generated"
    assert generated[0].provider == "mock"
    assert generated[0].model_id == "mock-teacher"
    prepared = prepare_examples(
        [
            generated[0].model_dump(),
            _family("alpha", scenario="scenario.alpha"),
            _family("beta", scenario="scenario.beta"),
        ],
        seed=1,
        heldout_fraction=0.5,
    )
    assert generated[0].example_id not in prepared.train_ids
    assert generated[0].example_id not in prepared.heldout_ids


def test_prepare_module_does_not_import_training() -> None:
    source = (
        Path(__file__).parents[1] / "experiments" / "tutor_data" / "prepare.py"
    ).read_text()
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not any("lora" in name or "tracing.train" in name for name in imported)
