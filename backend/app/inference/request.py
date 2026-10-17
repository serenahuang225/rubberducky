"""Assemble the final provider request and enforce provider ceilings on it.

The token and character budgets apply to the *assembled* request (system text, context and
learner text together, plus a fixed per-message framing allowance), and the output
reservation is subtracted from the provider's context window first. The context is fitted
into whatever remains; the final request is measured again with the same counter and is
refused, never silently truncated, if it still does not fit.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from app.db.repositories import ScopedRepository
from app.inference.context import build_tutor_context
from app.inference.tokens import DEFAULT_TOKEN_COUNTER, TokenCounter
from app.schemas.common import ContractModel
from app.schemas.context import ContextBudget, TutorContext

CONTEXT_HEADER = "Tutor context (JSON; cite only IDs that appear here):\n"
LEARNER_HEADER = "\n\nLearner said:\n"
_MAX_FIT_ATTEMPTS = 4


class ProviderBudget(ContractModel):
    """Ceilings for one provider call. Defaults suit a small local model, not tests."""

    schema_version: Literal["provider-budget.v1"] = "provider-budget.v1"
    context_window_tokens: Annotated[int, Field(ge=64, le=200_000)] = 8_192
    max_output_tokens: Annotated[int, Field(ge=1, le=8_192)] = 512
    max_request_chars: Annotated[int, Field(ge=64, le=800_000)] = 32_000
    # Allowance for chat-template framing (role markers, separators) per message.
    per_message_overhead_tokens: Annotated[int, Field(ge=0, le=64)] = 8


class ProviderMessage(ContractModel):
    role: Literal["system", "user"]
    content: str


class ProviderRequest(ContractModel):
    """Exactly what an adapter sends, with the measurements used to admit it."""

    schema_version: Literal["provider-request.v1"] = "provider-request.v1"
    messages: list[ProviderMessage]
    max_output_tokens: Annotated[int, Field(ge=1)]
    input_tokens: Annotated[int, Field(ge=0)]
    request_chars: Annotated[int, Field(ge=0)]
    token_counter: str
    budget: ProviderBudget


class ProviderBudgetError(ValueError):
    """The fixed parts of the request leave no room, or the final request does not fit."""


class InsufficientContextError(LookupError):
    """The budget cannot hold even the minimal context; report this, do not guess."""

    def __init__(self, context: TutorContext) -> None:
        super().__init__("context budget too small for the minimal tutor context")
        self.context = context


def _messages(system_text: str, context_text: str, user_text: str) -> list[ProviderMessage]:
    return [
        ProviderMessage(role="system", content=system_text),
        ProviderMessage(
            role="user", content=f"{CONTEXT_HEADER}{context_text}{LEARNER_HEADER}{user_text}"
        ),
    ]


def measure(
    messages: list[ProviderMessage], budget: ProviderBudget, counter: TokenCounter
) -> tuple[int, int]:
    """(input tokens, characters) of the assembled request under ``counter``."""
    tokens = sum(counter.count(m.content) for m in messages)
    tokens += budget.per_message_overhead_tokens * len(messages)
    return tokens, sum(len(m.content) for m in messages)


def _fits(tokens: int, chars: int, budget: ProviderBudget) -> bool:
    return (
        tokens + budget.max_output_tokens <= budget.context_window_tokens
        and chars <= budget.max_request_chars
    )


def build_provider_request(
    repo: ScopedRepository,
    *,
    concept_id: str,
    now: datetime,
    system_text: str,
    user_text: str,
    session_id: str | None = None,
    context_budget: ContextBudget | None = None,
    provider_budget: ProviderBudget | None = None,
    counter: TokenCounter = DEFAULT_TOKEN_COUNTER,
) -> tuple[ProviderRequest, TutorContext]:
    budget = provider_budget or ProviderBudget()
    fixed_tokens, fixed_chars = measure(_messages(system_text, "", user_text), budget, counter)
    token_room = budget.context_window_tokens - budget.max_output_tokens - fixed_tokens
    char_room = budget.max_request_chars - fixed_chars
    if token_room <= 0 or char_room <= 0:
        raise ProviderBudgetError("system and learner text leave no room for context")

    context: TutorContext | None = None
    for _ in range(_MAX_FIT_ATTEMPTS):
        context = build_tutor_context(
            repo,
            concept_id,
            now,
            session_id=session_id,
            budget=context_budget,
            counter=counter,
            max_chars=char_room,
            max_tokens=token_room,
        )
        if context.payload.sufficiency == "insufficient":
            raise InsufficientContextError(context)
        messages = _messages(system_text, context.serialized, user_text)
        tokens, chars = measure(messages, budget, counter)
        if _fits(tokens, chars, budget):
            request = ProviderRequest(
                messages=messages,
                max_output_tokens=budget.max_output_tokens,
                input_tokens=tokens,
                request_chars=chars,
                token_counter=counter.name,
                budget=budget,
            )
            return request, context
        # A tokenizer need not be additive across concatenation; tighten and refit.
        token_room -= max(0, tokens + budget.max_output_tokens - budget.context_window_tokens)
        char_room -= max(0, chars - budget.max_request_chars)
        token_room -= 1
        if token_room <= 0 or char_room <= 0:
            break
    raise ProviderBudgetError("assembled request exceeds the provider budget")
