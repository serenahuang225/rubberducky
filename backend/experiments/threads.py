"""Bound numeric libraries to the mission's two-thread ceiling."""

import contextlib
import os

import torch

_THREAD_ENV = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def limit_numerical_threads(count: int = 2) -> int:
    """Use at most two numerical threads. Returns the applied count."""

    if count < 1 or count > 2:
        raise ValueError("numerical threads must be 1 or 2")
    for name in _THREAD_ENV:
        os.environ[name] = str(count)
    torch.set_num_threads(count)
    # Interop threads can only be set once, and only before parallel work starts.
    with contextlib.suppress(RuntimeError):
        torch.set_num_interop_threads(1)
    return count
