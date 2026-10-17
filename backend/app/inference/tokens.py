"""Token counting conventions used to enforce provider budgets.

The default counter is a deliberate upper bound: it counts UTF-8 bytes. Byte-level BPE
tokenizers (GPT-2 style, SmolLM2, Llama-family, Claude) never emit a token that covers zero
bytes, so a text's byte count is at least its token count. A provider adapter with a real
tokenizer can pass an exact counter instead; budgets are then enforced with that count.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class TokenCounter(Protocol):
    @property
    def name(self) -> str: ...

    def count(self, text: str) -> int: ...


@dataclass(frozen=True)
class Utf8ByteTokenCounter:
    name: str = "utf8-bytes-upper-bound.v1"

    def count(self, text: str) -> int:
        return len(text.encode("utf-8"))


@dataclass(frozen=True)
class CallableTokenCounter:
    """Wraps a tokenizer, e.g. ``lambda t: len(tokenizer.encode(t))``."""

    name: str
    counter: Callable[[str], int]

    def count(self, text: str) -> int:
        value = self.counter(text)
        if value < 0:
            raise ValueError("token counter returned a negative count")
        return value


DEFAULT_TOKEN_COUNTER = Utf8ByteTokenCounter()
