"""Byte-level encoding and completion-only labels.

Prompt tokens and padding use ignore index -100. Only completion tokens are training targets.
This encoding is for the offline smoke; it is not a downloaded tokenizer.
"""

from collections.abc import Sequence
from dataclasses import dataclass

PAD_ID = 0
BOS_ID = 1
EOS_ID = 2
IGNORE_INDEX = -100


@dataclass(frozen=True)
class EncodedPair:
    token_ids: list[int]
    prompt_len: int
    pad_id: int


def encode_text(text: str, *, vocab_size: int = 64) -> list[int]:
    if vocab_size < 8:
        raise ValueError("vocab_size must leave room for special tokens")
    span = vocab_size - 4
    ids = [BOS_ID]
    ids.extend(3 + (ord(character) % span) for character in text)
    ids.append(EOS_ID)
    return ids


def encode_pair(prompt: str, completion: str, *, vocab_size: int = 64) -> EncodedPair:
    prompt_ids = encode_text(prompt, vocab_size=vocab_size)
    completion_ids = encode_text(completion, vocab_size=vocab_size)[1:]
    return EncodedPair(
        token_ids=[*prompt_ids, *completion_ids],
        prompt_len=len(prompt_ids),
        pad_id=PAD_ID,
    )


def completion_only_labels(
    token_ids: Sequence[int], prompt_len: int, *, pad_id: int
) -> list[int]:
    """Ignore the prompt and any padding. Completion token ids stay as labels."""

    labels: list[int] = []
    for index, token in enumerate(token_ids):
        if index < prompt_len or token == pad_id:
            labels.append(IGNORE_INDEX)
        else:
            labels.append(token)
    return labels
