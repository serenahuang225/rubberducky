"""Failure type shared by the generation and check adapters.

Only a stable code leaves an adapter. Provider, subprocess and sandbox text can carry
secrets or learner context, so it is never copied into the exception message.
"""

from app.schemas.interactives import FallbackReason


class InteractiveError(Exception):
    def __init__(self, code: FallbackReason) -> None:
        super().__init__(code)
        self.code: FallbackReason = code
