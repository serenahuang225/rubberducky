"""Validate and split shared tutoring examples by scenario/problem/concept family.

Held-out families are chosen before any training file is written. Malformed, private,
unreviewed, undocumented public and cross-split rows are excluded with a reason. Nothing
in this module downloads data or starts training.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from pydantic import ValidationError

from experiments.tutor_data.contracts import SharedExample, family_key
from experiments.tutor_data.masks import completion_only_labels, encode_pair

Record = Mapping[str, object]


@dataclass(frozen=True)
class ExcludedExample:
    example_id: str
    reason: str


@dataclass
class ValidationReport:
    accepted_ids: list[str]
    excluded: list[ExcludedExample]
    download_count: int = 0


@dataclass
class PreparationResult:
    train_ids: list[str]
    heldout_ids: list[str]
    excluded: list[ExcludedExample]
    family_by_id: dict[str, str]
    dry_run: bool
    download_count: int = 0
    train_examples: list[SharedExample] = field(default_factory=list)
    heldout_examples: list[SharedExample] = field(default_factory=list)


def validate_examples(path: Path) -> ValidationReport:
    records = load_jsonl(path)
    accepted: list[str] = []
    excluded: list[ExcludedExample] = []
    for record in records:
        example_id, reason, example = _classify(record)
        if reason is None and example is not None:
            accepted.append(example_id)
        elif reason is not None:
            excluded.append(ExcludedExample(example_id, reason))
    return ValidationReport(accepted_ids=accepted, excluded=excluded, download_count=0)


def prepare_examples(
    records: Path | Sequence[object],
    *,
    seed: int,
    heldout_fraction: float,
    output_dir: Path | None = None,
    dry_run: bool = False,
) -> PreparationResult:
    raw_records = load_jsonl(records) if isinstance(records, Path) else list(records)
    excluded: list[ExcludedExample] = []
    accepted: list[SharedExample] = []
    for record in raw_records:
        example_id, reason, example = _classify(_as_mapping(record))
        if reason is not None or example is None:
            excluded.append(ExcludedExample(example_id, reason or "malformed"))
            continue
        accepted.append(example)
    leaked = _cross_split_ids(accepted)
    if leaked:
        excluded.extend(
            ExcludedExample(example_id, "cross_split_family") for example_id in sorted(leaked)
        )
        accepted = [example for example in accepted if example.example_id not in leaked]
    components = _related_components(accepted)
    if heldout_fraction < 0 or heldout_fraction > 1:
        raise ValueError("heldout_fraction must be between 0 and 1")
    if heldout_fraction > 0 and len(components) < 2:
        raise ValueError("at least two families are required to separate a held-out family")
    component_keys = [_component_key(group) for group in components]
    heldout_keys = _holdout_families(component_keys, fraction=heldout_fraction, seed=seed)
    train_examples: list[SharedExample] = []
    heldout_examples: list[SharedExample] = []
    for group, key in zip(components, component_keys, strict=True):
        if key in heldout_keys:
            heldout_examples.extend(group)
        else:
            train_examples.extend(group)
    result = PreparationResult(
        train_ids=[example.example_id for example in train_examples],
        heldout_ids=[example.example_id for example in heldout_examples],
        excluded=excluded,
        family_by_id={example.example_id: family_key(example) for example in accepted},
        dry_run=dry_run,
        train_examples=train_examples,
        heldout_examples=heldout_examples,
    )
    if output_dir is not None:
        _write(output_dir, result)
    return result


def load_jsonl(path: Path) -> list[object]:
    records: list[object] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            records.append({"example_id": f"line.{line_number}", "_parse_error": str(error)})
    return records


def _as_mapping(record: object) -> Mapping[str, object] | object:
    if isinstance(record, SharedExample):
        return record.model_dump()
    return record


def _classify(record: object) -> tuple[str, str | None, SharedExample | None]:
    if not isinstance(record, Mapping):
        return "<malformed>", "malformed", None
    if "_parse_error" in record:
        return _label(record), "malformed", None
    required = (
        "example_id",
        "terms",
        "license",
        "review_status",
        "scenario_family",
        "problem_family",
        "concept_family",
        "prompt",
        "completion",
        "provenance",
    )
    if any(field not in record for field in required):
        return _label(record), "malformed", None
    source = record.get("source")
    if not isinstance(source, str) or source == "":
        return _label(record), "missing_source", None
    try:
        example = SharedExample.model_validate(dict(record))
    except ValidationError:
        return _label(record), "malformed", None
    if example.learner_id and not example.private and example.provenance != "learner_recording":
        return example.example_id, "per_learner_finetune", None
    if example.private or example.provenance == "learner_recording":
        return example.example_id, "private_learner_or_recording", None
    documented = bool(example.license_access and example.field_mapping)
    if example.provenance == "public_dataset" and not documented:
        return example.example_id, "public_dataset_missing_documentation", None
    if example.review_status != "reviewed":
        return example.example_id, "unreviewed", None
    return example.example_id, None, example


def _label(record: Mapping[str, object]) -> str:
    example_id = record.get("example_id")
    if isinstance(example_id, str) and example_id:
        return example_id
    return "<malformed>"


def _cross_split_ids(examples: Sequence[SharedExample]) -> set[str]:
    declared: dict[str, set[str]] = {}
    members: dict[str, list[str]] = {}
    for example in examples:
        key = family_key(example)
        members.setdefault(key, []).append(example.example_id)
        if example.declared_split is not None:
            declared.setdefault(key, set()).add(example.declared_split)
    leaked: set[str] = set()
    for key, splits in declared.items():
        if "train" in splits and "held_out" in splits:
            leaked.update(members[key])
    return leaked


def _component_key(members: Sequence[SharedExample]) -> str:
    return "|".join(sorted(example.example_id for example in members))


def _related_components(examples: Sequence[SharedExample]) -> list[list[SharedExample]]:
    """Group rows that share a scenario, problem or concept family.

    A family is not split across train and held-out. Sharing any of the three identifiers
    links the rows, so near-duplicate algebra items stay on one side.
    """

    parent = {example.example_id: example.example_id for example in examples}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: str, right: str) -> None:
        parent[find(left)] = find(right)

    buckets: dict[tuple[str, str], list[str]] = {}
    for example in examples:
        for kind, value in (
            ("scenario", example.scenario_family),
            ("problem", example.problem_family),
            ("concept", example.concept_family),
        ):
            buckets.setdefault((kind, value), []).append(example.example_id)
    for members in buckets.values():
        first = members[0]
        for other in members[1:]:
            union(first, other)
    grouped: dict[str, list[SharedExample]] = {}
    for example in examples:
        grouped.setdefault(find(example.example_id), []).append(example)
    return [grouped[key] for key in sorted(grouped)]


def _holdout_families(families: Sequence[str], *, fraction: float, seed: int) -> set[str]:
    if not families or fraction == 0:
        return set()
    order = np.random.default_rng(seed).permutation(len(families))
    count = round(len(families) * fraction)
    count = min(max(count, 1), len(families) - 1)
    chosen = order[:count]
    return {families[index] for index in chosen}


def _write(directory: Path, result: PreparationResult) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "dry_run": result.dry_run,
        "download_count": result.download_count,
        "train_ids": result.train_ids,
        "heldout_ids": result.heldout_ids,
        "excluded": [
            {"example_id": item.example_id, "reason": item.reason} for item in result.excluded
        ],
        "per_learner_finetune": False,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    if result.dry_run:
        return
    _write_jsonl(directory / "train.jsonl", result.train_examples)
    _write_jsonl(directory / "heldout.jsonl", result.heldout_examples)
    masks = []
    for example in result.train_examples:
        encoded = encode_pair(example.prompt, example.completion)
        labels = completion_only_labels(
            encoded.token_ids, encoded.prompt_len, pad_id=encoded.pad_id
        )
        masks.append(
            {
                "example_id": example.example_id,
                "prompt_len": encoded.prompt_len,
                "labels": labels,
            }
        )
    (directory / "masks.json").write_text(json.dumps(masks, indent=2) + "\n")


def _write_jsonl(path: Path, examples: Sequence[SharedExample]) -> None:
    lines = [example.model_dump_json() for example in examples]
    path.write_text(("\n".join(lines) + "\n") if lines else "")
