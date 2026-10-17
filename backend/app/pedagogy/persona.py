"""Persona phrasing for deterministic tutor text.

Appearance never changes wording or assessment. Personality changes only tone, and every
variant stays kind: playful or mildly sassy remarks are about the problem, never about the
learner. A comfort override takes effect immediately.
"""

from typing import Literal

from app.schemas.learner import Appearance, ComfortOverride, Personality

APPEARANCES: tuple[Appearance, ...] = ("animal", "older_adult", "younger_adult")
PERSONALITIES: tuple[Personality, ...] = ("gentle", "matter_of_fact", "playful", "mildly_sassy")
COMFORT_OVERRIDES: tuple[ComfortOverride, ...] = ("none", "neutral_supportive", "reduced_sass")

Tone = Literal["neutral", "correction", "success", "support"]

_OPENERS: dict[Personality, dict[Tone, str]] = {
    "gentle": {
        "neutral": "",
        "correction": "Thanks for showing your step. ",
        "success": "Nice work. ",
        "support": "That's okay. ",
    },
    "matter_of_fact": {
        "neutral": "",
        "correction": "Let's check one part. ",
        "success": "That checks out. ",
        "support": "No problem. ",
    },
    "playful": {
        "neutral": "Puzzle time! ",
        "correction": "Ooh, this one has a sneaky spot. ",
        "success": "Yes! ",
        "support": "No worries, tricky ones are the fun ones. ",
    },
    "mildly_sassy": {
        "neutral": "Right, let's do this. ",
        "correction": "Those parentheses are being sneaky again. ",
        "success": "Look at that, the equation behaved. ",
        "support": "Fair enough, parentheses can be a lot. ",
    },
}


def effective_personality(personality: Personality, comfort: ComfortOverride) -> Personality:
    if comfort == "neutral_supportive":
        return "gentle"
    if comfort == "reduced_sass" and personality == "mildly_sassy":
        return "matter_of_fact"
    return personality


def opener(personality: Personality, comfort: ComfortOverride, tone: Tone) -> str:
    return _OPENERS[effective_personality(personality, comfort)][tone]
