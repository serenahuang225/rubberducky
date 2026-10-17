"""Common surface of the production adapters (local Transformers, endpoint, Claude).

``draft`` satisfies the coordinator's synchronous :class:`TutorProvider` protocol and runs
in the request's worker thread. ``adraft`` is the same call for async callers: the blocking
work runs in a thread so the event loop (and health checks) stay responsive, and an asyncio
cancellation is turned into the call's cancel token so it stops cooperatively.
"""

import asyncio
from abc import ABC, abstractmethod

from app.inference.events import AdapterCapabilities, DraftOutcome
from app.inference.providers import DraftInputs
from app.schemas.tutor import ProviderLabel, TutorDraft


class DraftAdapter(ABC):
    name: str

    @abstractmethod
    def label(self) -> ProviderLabel: ...

    @abstractmethod
    def capabilities(self) -> AdapterCapabilities: ...

    @abstractmethod
    def draft_outcome(self, inputs: DraftInputs) -> DraftOutcome: ...

    def draft(self, inputs: DraftInputs) -> TutorDraft:
        return self.draft_outcome(inputs).draft

    async def adraft(self, inputs: DraftInputs) -> DraftOutcome:
        try:
            return await asyncio.to_thread(self.draft_outcome, inputs)
        except asyncio.CancelledError:
            inputs.cancel.cancel("asyncio-cancelled")
            raise
