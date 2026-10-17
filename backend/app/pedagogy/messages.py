"""Concise public wording for each policy action, used by the deterministic mock provider.

Wording is chosen from the plan only. It never contains the solution or the completed step
before the learner has produced them; the coordinator also checks that independently.
"""

from app.pedagogy.persona import opener
from app.pedagogy.policy import TurnPlan

_CRITERION_PHRASES = {
    "multiplies_each_term": "the outside factor multiplies every term",
    "groups_as_repeated_addition": "2(x + 3) is two groups of (x + 3)",
    "preserves_value": "the rewrite keeps the same value",
}


def _check_in(plan: TurnPlan) -> str:
    p = plan.message_params
    parts = []
    if p.get("energy") in ("tired", "a_bit_tired"):
        parts.append("Thanks for telling me. We'll go slower today, one small step at a time.")
    elif p.get("energy") == "ready":
        parts.append("Glad you're ready.")
    if p.get("returning") == "yes":
        parts.append("Last time, grouping both terms helped after a hint.")
    if p.get("kind") == "explanation":
        parts.append(f"Here's our task: {p['statement']} A sentence or two is plenty.")
    else:
        parts.append(f"Here's the problem: {p['statement']}. What's your first step?")
    return " ".join(parts)


def _diagnostic(plan: TurnPlan) -> str:
    p = plan.message_params
    if p.get("level") == "2":
        return (
            f"Picture {p['factor']}{p['group']} as {p['factor']} groups of {p['group']}. "
            "What happens to the second term inside?"
        )
    return (
        f"Look at the {p['factor']} outside {p['group']}. Does it multiply only the first "
        "term, or every term inside?"
    )


def _step_feedback(plan: TurnPlan) -> str:
    p = plan.message_params
    text = f"\u201c{p['step']}\u201d keeps the equation balanced."
    if p.get("expanded") == "yes" and p.get("factor"):
        text += f" The {p['factor']} now multiplies both terms."
    return text + " What's your next step?"


def _reasoning_check(plan: TurnPlan) -> str:
    p = plan.message_params
    if "unresolved" in p:
        return (
            f"{p['value']} does work, but the step \u201c{p['unresolved']}\u201d doesn't lead "
            "there. Which step got you to this value?"
        )
    return f"{p['value']} does work. Show me one step that gets there, so we can check the method."


def _success_praise(plan: TurnPlan) -> str:
    if plan.message_params.get("assisted") == "yes":
        return "You finished it with steps that check out, after we looked at the grouping."
    return "You solved it on your own with steps that check out."


def _explanation_feedback(plan: TurnPlan) -> str:
    met = [m for m in plan.message_params.get("met", "").split(",") if m]
    phrases = [_CRITERION_PHRASES[m] for m in met if m in _CRITERION_PHRASES]
    said = " and ".join(phrases) if phrases else "the key idea"
    return f"You explained that {said}. That's the heart of distribution."


def _explanation_follow_up(plan: TurnPlan) -> str:
    met = [m for m in plan.message_params.get("met", "").split(",") if m]
    start = "You're on your way." if met else "Thanks. A number alone doesn't explain why yet."
    return f"{start} {plan.message_params['question']}"


def render_utterance(plan: TurnPlan) -> str:
    p = plan.message_params
    match plan.action_type:
        case "check_in_and_pose":
            body = _check_in(plan)
        case "confirm_ink":
            body = (
                "I can see handwriting, but I won't guess what it says. Please type it or "
                "confirm it so I can check it."
            )
        case "ask_rephrase":
            body = (
                "I can't check that form yet, so I'm not calling it right or wrong. Could you "
                "write it with numbers, a variable, + - and =?"
            )
        case "step_feedback":
            body = _step_feedback(plan)
        case "diagnostic_hint":
            body = _diagnostic(plan)
        case "step_not_equivalent":
            body = (
                "That step changes what the equation says. Which operation did you use, and "
                "did it happen to both sides?"
            )
        case "reasoning_check":
            body = _reasoning_check(plan)
        case "solution_feedback":
            body = (
                f"Let's test it: put {p['claim']} back into {p['statement']}. "
                "Do both sides match?"
            )
        case "feedback_and_transfer":
            body = f"{_success_praise(plan)} Now a fresh one: {p['next_statement']}."
        case "transfer_feedback_and_explain":
            body = (
                f"{_success_praise(plan)} One more thing: {p['next_statement']} "
                "A sentence or two is plenty."
            )
        case "explanation_feedback":
            body = f"{_explanation_feedback(plan)} Another problem, or stop here?"
        case "explanation_follow_up":
            body = _explanation_follow_up(plan)
        case "wrap_up":
            body = f"{_success_praise(plan)} That's today's set. You can finish here."
    return (opener(plan.personality, plan.comfort_override, plan.tone) + body).strip()
