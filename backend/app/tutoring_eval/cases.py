"""The built-in fixture evaluation set: a few authored fictional learner timelines.

These cases are small by design. They exercise the rubric and the replay cutoff, not a
learner population, so scores over them say nothing about real tutoring quality. Every
timeline deliberately holds events *after* some turns (the ``future.*`` sources); a correct
replay never shows them to an earlier turn.
"""

from datetime import UTC, datetime, timedelta

from app.tutoring_eval.contracts import (
    HistoryEvent,
    HistoryKind,
    ReplayCase,
    ReplayTurn,
    TurnExpectation,
)

CASE_SET_VERSION = "tutoring-fixture-cases.v1"
_BASE = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)


def _at(day: int, minute: int = 0) -> datetime:
    return _BASE + timedelta(days=day, minutes=minute)


def _event(source_id: str, day: int, minute: int, kind: HistoryKind, text: str) -> HistoryEvent:
    return HistoryEvent(source_id=source_id, occurred_at=_at(day, minute), kind=kind, text=text)


def _turn(
    turn_id: str,
    day: int,
    minute: int,
    message: str,
    statement: str,
    expectation: TurnExpectation,
) -> ReplayTurn:
    return ReplayTurn(
        turn_id=turn_id,
        occurred_at=_at(day, minute),
        learner_message=message,
        problem_statement=statement,
        expectation=expectation,
    )


_DISTRIBUTION = "2(x + 3) = 14"
_PARTIAL_WRONG = ["2(x+3)=2x+3"]
_FINISHED_STEP = ["2x+6", "x=4"]
_TRUE_STEPS = ["2(x+3)=2x+6", "2x+6=14", "2x=8", "x=4"]


def _partial_distribution() -> ReplayCase:
    return ReplayCase(
        case_id="case.partial-distribution",
        title="Distributes the 2 over only the first term",
        scenario="partial_distribution",
        history=[
            _event(
                "hist.pd.1", 0, 0, "assessment", "Solved x + 5 = 9 independently and correctly."
            ),
            _event(
                "hist.pd.2", 2, 0, "tutor_hint", "Asked what the 2 outside the bracket multiplies."
            ),
            _event("hist.pd.3", 2, 5, "learner_work", "Wrote 2x + 3 = 14 for 2(x + 3) = 14."),
            _event("hist.pd.4", 2, 10, "learner_message", "I only multiplied the x, I think."),
            _event("future.pd.5", 9, 0, "assessment", "Distributed 3(y + 1) correctly next week."),
        ],
        turns=[
            _turn(
                "turn.pd.1",
                2,
                6,
                "My next line is 2x + 3 = 14.",
                _DISTRIBUTION,
                TurnExpectation(
                    wrong_claims=_PARTIAL_WRONG,
                    correct_claims=_TRUE_STEPS,
                    answer_strings=_FINISHED_STEP,
                    diagnostic_cues=[["both terms", "each term", "the 3", "x and the 3"]],
                    anchors=["2", "x + 3"],
                    expects_hint=True,
                ),
            ),
            _turn(
                "turn.pd.2",
                2,
                11,
                "Hmm, so what do I do with the 3?",
                _DISTRIBUTION,
                TurnExpectation(
                    wrong_claims=_PARTIAL_WRONG,
                    correct_claims=_TRUE_STEPS,
                    answer_strings=_FINISHED_STEP,
                    diagnostic_cues=[["3"], ["2 groups", "two groups", "both"]],
                    anchors=["2", "3", "groups"],
                    expects_hint=True,
                    expected_memory_source_ids=["hist.pd.4"],
                ),
            ),
        ],
    )


def _right_answer_weak_method() -> ReplayCase:
    return ReplayCase(
        case_id="case.right-answer-weak-method",
        title="Correct value with an unexplained method",
        scenario="correct_value_questionable_method",
        history=[
            _event("hist.rw.1", 1, 0, "learner_work", "Wrote x = 4 with no working shown."),
            _event("hist.rw.2", 1, 2, "learner_message", "I just tried numbers until one worked."),
            _event("future.rw.3", 6, 0, "assessment", "Showed full working on a later problem."),
        ],
        turns=[
            _turn(
                "turn.rw.1",
                1,
                3,
                "The answer is x = 4.",
                _DISTRIBUTION,
                TurnExpectation(
                    correct_claims=_TRUE_STEPS,
                    diagnostic_cues=[["how", "what did you do", "walk me through"], ["4", "x = 4"]],
                    anchors=["4"],
                    expected_memory_source_ids=["hist.rw.2"],
                ),
            )
        ],
    )


def _just_tell_me() -> ReplayCase:
    return ReplayCase(
        case_id="case.just-tell-me",
        title="Asks to be told, then asks for an explanation",
        scenario="just_tell_me",
        history=[
            _event("hist.jt.1", 3, 0, "tutor_hint", "Asked which terms sit inside the bracket."),
            _event("hist.jt.2", 3, 2, "learner_message", "I don't know."),
            _event("hist.jt.3", 3, 4, "tutor_hint", "Drew two groups of x + 3 as a picture."),
            _event("future.jt.4", 8, 0, "learner_work", "Finished a similar problem alone."),
        ],
        turns=[
            _turn(
                "turn.jt.1",
                3,
                1,
                "Just tell me the answer.",
                _DISTRIBUTION,
                TurnExpectation(
                    answer_strings=_FINISHED_STEP,
                    anchors=["2", "bracket"],
                    expects_hint=True,
                    acknowledge_state=True,
                    max_words=45,
                ),
            ),
            _turn(
                "turn.jt.2",
                3,
                5,
                "Please explain it, I'm still lost.",
                _DISTRIBUTION,
                TurnExpectation(
                    correct_claims=_TRUE_STEPS,
                    answer_strings=_FINISHED_STEP,
                    allow_explanation=True,
                    anchors=["2", "3", "groups"],
                    expects_hint=True,
                    max_words=70,
                    expected_memory_source_ids=["hist.jt.3"],
                ),
            ),
        ],
    )


def _tired() -> ReplayCase:
    return ReplayCase(
        case_id="case.tired",
        title="Says they are tired",
        scenario="tiredness",
        history=[
            _event("hist.ti.1", 4, 0, "self_report", "Said they are tired after school today."),
            _event("future.ti.2", 11, 0, "self_report", "Said they felt energetic."),
        ],
        turns=[
            _turn(
                "turn.ti.1",
                4,
                2,
                "I'm tired but I guess I can try.",
                _DISTRIBUTION,
                TurnExpectation(
                    answer_strings=_FINISHED_STEP,
                    anchors=["one", "small"],
                    expects_hint=True,
                    acknowledge_state=True,
                    max_words=45,
                    expected_memory_source_ids=["hist.ti.1"],
                ),
            )
        ],
    )


def _ambiguous_handwriting() -> ReplayCase:
    return ReplayCase(
        case_id="case.ambiguous-handwriting",
        title="Handwriting could be read two ways",
        scenario="ambiguous_handwriting",
        history=[
            _event("hist.ah.1", 5, 0, "learner_work", "Strokes read as 2x + 3 or 2x + 8; unclear."),
            _event("future.ah.2", 12, 0, "learner_message", "Typed corrections are easier."),
        ],
        turns=[
            _turn(
                "turn.ah.1",
                5,
                1,
                "(wrote a line the board could not read clearly)",
                _DISTRIBUTION,
                TurnExpectation(
                    wrong_claims=["thatiswrong", "you made a mistake"],
                    diagnostic_cues=[["is that", "read this as", "did you write", "confirm"]],
                    anchors=["2x", "3"],
                    expected_memory_source_ids=["hist.ah.1"],
                ),
            )
        ],
    )


def _assisted_success() -> ReplayCase:
    return ReplayCase(
        case_id="case.assisted-success",
        title="Succeeds after hints",
        scenario="assisted_success",
        history=[
            _event("hist.as.1", 6, 0, "tutor_hint", "Gave the groups picture for 2(x + 3)."),
            _event("hist.as.2", 6, 6, "learner_work", "Wrote 2x + 6 = 14 after the picture."),
            _event("future.as.3", 13, 0, "assessment", "Solved a fresh problem independently."),
        ],
        turns=[
            _turn(
                "turn.as.1",
                6,
                7,
                "I got 2x + 6 = 14!",
                _DISTRIBUTION,
                TurnExpectation(
                    correct_claims=_TRUE_STEPS,
                    diagnostic_cues=[["new problem", "another one", "similar", "fresh"]],
                    anchors=["groups", "picture", "2x + 6"],
                    expected_memory_source_ids=["hist.as.1"],
                ),
            )
        ],
    )


def _silence() -> ReplayCase:
    return ReplayCase(
        case_id="case.silence",
        title="No input for a while",
        scenario="silence",
        history=[
            _event("hist.si.1", 7, 0, "preference", "Likes pictures better than formulas."),
            _event("future.si.2", 14, 0, "preference", "Now prefers a quieter board."),
        ],
        turns=[
            _turn(
                "turn.si.1",
                7,
                3,
                "(no input for 90 seconds)",
                _DISTRIBUTION,
                TurnExpectation(
                    answer_strings=_FINISHED_STEP,
                    anchors=["picture", "2"],
                    expects_hint=True,
                    max_words=40,
                    expected_memory_source_ids=["hist.si.1"],
                ),
            )
        ],
    )


def build_fixture_cases() -> list[ReplayCase]:
    return [
        _partial_distribution(),
        _right_answer_weak_method(),
        _just_tell_me(),
        _tired(),
        _ambiguous_handwriting(),
        _assisted_success(),
        _silence(),
    ]
