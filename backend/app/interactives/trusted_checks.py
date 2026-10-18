"""Repository-owned, dependency-free trusted checks for an ``ExplanationSpec``.

This file is deliberately standard-library only and independent of the Pydantic contract: it
is uploaded verbatim into the Daytona sandbox and also run locally, so a candidate is judged
by two implementations of the same rules (strict structure, bounds, safe text) plus the math
the native components rely on. The candidate supplies the data; it never supplies a check.

Run as a script: ``python trusted_checks.py spec.json`` prints one JSON report line and exits
0 only when every check passed.
"""

import hashlib
import json
import re
import sys
from typing import Any

SPEC_VERSION = "explanation-spec.v1"
RESULT_VERSION = "trusted-check-result.v1"
MIN_FACTOR = 1
MAX_FACTOR = 12
MAX_SPEC_JSON_CHARS = 2_000
# The largest figure any component draws (12 x (12 + 12) cells).
MAX_RENDERED_CELLS = 288

CHECK_NAMES = ("schema", "bounds", "plain_text", "layout_math", "render_cap")

_CONCEPTS = ("concept.distribution", "concept.grouping")
_TEXT_LIMITS = {"title": 80, "prompt": 160, "caption": 240}
_FORBIDDEN_TEXT = re.compile(
    r"[<>{}\[\]\\`$|]|[\x00-\x1f\x7f]|://|(?i:javascript:|data:|www\.|https?|file:|\.com\b)"
)
_RANGE_KEYS = {"min", "max", "initial"}
_COMPONENT_RANGES = {
    "grouping": ("groups", "per_group"),
    "distribution": ("outer", "left", "right"),
}


def canonical_digest(spec: object) -> str:
    text = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def grouping_layout(groups: int, per_group: int) -> list[int]:
    """Sizes of the drawn groups: ``groups`` groups of ``per_group`` items."""
    return [per_group] * groups


def distribution_layout(outer: int, left: int, right: int) -> tuple[int, int, int]:
    """Cells of the left rectangle, right rectangle and the combined ``outer x (left+right)``."""
    return outer * left, outer * right, outer * (left + right)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _range_values(raw: object) -> tuple[int, int, int] | None:
    if not isinstance(raw, dict) or set(raw) != _RANGE_KEYS:
        return None
    if not all(_is_int(raw[key]) for key in _RANGE_KEYS):
        return None
    return raw["min"], raw["max"], raw["initial"]


def _ranges(manipulative: dict[str, Any]) -> dict[str, tuple[int, int, int]] | None:
    names = _COMPONENT_RANGES.get(manipulative.get("component", ""))
    if names is None:
        return None
    found: dict[str, tuple[int, int, int]] = {}
    for name in names:
        values = _range_values(manipulative.get(name))
        if values is None:
            return None
        found[name] = values
    return found


def _check_schema(spec: object) -> tuple[bool, str]:
    if not isinstance(spec, dict):
        return False, "spec is not an object"
    expected = {"schema_version", "concept_id", "title", "prompt", "caption", "manipulative"}
    if set(spec) != expected:
        return False, "unexpected or missing top-level fields"
    if spec["schema_version"] != SPEC_VERSION or spec["concept_id"] not in _CONCEPTS:
        return False, "unsupported version or concept"
    manipulative = spec["manipulative"]
    if not isinstance(manipulative, dict):
        return False, "manipulative is not an object"
    component = manipulative.get("component")
    if component not in _COMPONENT_RANGES:
        return False, "unknown component"
    keys = {"component", *_COMPONENT_RANGES[component]}
    if component == "grouping":
        keys.add("item_label")
    if set(manipulative) != keys:
        return False, "unexpected or missing component fields"
    if _ranges(manipulative) is None:
        return False, "ranges must be {min,max,initial} integers"
    if component == "grouping" and not isinstance(manipulative["item_label"], str):
        return False, "item_label must be text"
    if not all(isinstance(spec[name], str) for name in _TEXT_LIMITS):
        return False, "title, prompt and caption must be text"
    return True, "strict structure"


def _check_bounds(spec: dict[str, Any]) -> tuple[bool, str]:
    ranges = _ranges(spec["manipulative"]) or {}
    for name, (low, high, initial) in ranges.items():
        if not (MIN_FACTOR <= low <= initial <= high <= MAX_FACTOR):
            return False, f"{name} needs {MIN_FACTOR} <= min <= initial <= max <= {MAX_FACTOR}"
    return True, f"every range within {MIN_FACTOR}..{MAX_FACTOR}"


def _check_text(spec: dict[str, Any]) -> tuple[bool, str]:
    texts = {name: spec[name] for name in _TEXT_LIMITS}
    manipulative = spec["manipulative"]
    if manipulative["component"] == "grouping":
        texts["item_label"] = manipulative["item_label"]
        limits = {**_TEXT_LIMITS, "item_label": 24}
    else:
        limits = _TEXT_LIMITS
    for name, text in texts.items():
        if not text or len(text) > limits[name] or text != text.strip():
            return False, f"{name} has an invalid length or surrounding space"
        if _FORBIDDEN_TEXT.search(text):
            return False, f"{name} contains markup, a link or control characters"
    return True, "plain words only"


def _positions(low: int, high: int) -> range:
    return range(low, high + 1)


def _check_layout_math(spec: dict[str, Any]) -> tuple[bool, str]:
    manipulative = spec["manipulative"]
    ranges = _ranges(manipulative) or {}
    if manipulative["component"] == "grouping":
        groups, per_group = ranges["groups"], ranges["per_group"]
        for g in _positions(groups[0], groups[1]):
            for p in _positions(per_group[0], per_group[1]):
                sizes = grouping_layout(g, p)
                if len(sizes) != g or any(size != p for size in sizes) or sum(sizes) != g * p:
                    return False, f"{g} groups of {p} do not add up to {g * p}"
        return True, "groups x items equals the drawn total at every position"
    outer, left, right = ranges["outer"], ranges["left"], ranges["right"]
    for a in _positions(outer[0], outer[1]):
        for b in _positions(left[0], left[1]):
            for c in _positions(right[0], right[1]):
                left_cells, right_cells, whole = distribution_layout(a, b, c)
                if left_cells + right_cells != whole or whole != a * b + a * c:
                    return False, f"{a} x ({b} + {c}) differs from {a} x {b} + {a} x {c}"
    return True, "a(b + c) equals ab + ac at every position"


def _check_render_cap(spec: dict[str, Any]) -> tuple[bool, str]:
    manipulative = spec["manipulative"]
    ranges = _ranges(manipulative) or {}
    if manipulative["component"] == "grouping":
        worst = ranges["groups"][1] * ranges["per_group"][1]
    else:
        worst = ranges["outer"][1] * (ranges["left"][1] + ranges["right"][1])
    if worst > MAX_RENDERED_CELLS:
        return False, f"draws up to {worst} cells, more than {MAX_RENDERED_CELLS}"
    return True, f"draws at most {worst} cells"


def check_spec(spec: object) -> dict[str, Any]:
    """Run every check; later checks are skipped as failed when the structure is unusable."""
    schema_ok, schema_detail = _check_schema(spec)
    results: list[tuple[str, bool, str]] = [("schema", schema_ok, schema_detail)]
    dependent = (
        ("bounds", _check_bounds),
        ("plain_text", _check_text),
        ("layout_math", _check_layout_math),
        ("render_cap", _check_render_cap),
    )
    for name, check in dependent:
        if not schema_ok:
            results.append((name, False, "skipped: an earlier structural check failed"))
            continue
        assert isinstance(spec, dict)  # noqa: S101 - narrowed by the schema check above
        ok, detail = check(spec)
        results.append((name, ok, detail))
        if name == "bounds" and not ok:
            schema_ok = False
    return {
        "schema_version": RESULT_VERSION,
        "spec_digest": canonical_digest(spec),
        "passed": all(ok for _, ok, _ in results),
        "checks": [{"name": n, "passed": ok, "detail": d[:200]} for n, ok, d in results],
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(json.dumps({"error": "usage: trusted_checks.py spec.json"}))
        return 2
    with open(argv[1], encoding="utf-8") as handle:
        text = handle.read(MAX_SPEC_JSON_CHARS + 1)
    if len(text) > MAX_SPEC_JSON_CHARS:
        print(json.dumps({"error": "spec exceeds the payload limit"}))
        return 2
    try:
        spec = json.loads(text)
    except ValueError:
        print(json.dumps({"error": "spec is not JSON"}))
        return 2
    report = check_spec(spec)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
