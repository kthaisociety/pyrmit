"""
An answer, its chunks and a scripted decision model (Jev) for tests of the claim check (agentic.claim_check) and the
chat that runs it.

RAW cites A for the house rule and B for the fee; A states the house rule, B does not state the fee.
"""

import threading
import time

A, B, C = "a" * 16, "b" * 16, "c" * 16
CHUNKS = {
    A: {"chunk_id": A, "kind": "law", "title": "PBL", "section": "9 kap. 4 §", "header": "PBL 9 kap. 4 §",
        "text": "Bygglov krävs för nybyggnad av en byggnad."},
    B: {"chunk_id": B, "kind": "local", "kommun": "Ydre", "title": "Bygglovstaxa", "header": "Ydre – Bygglovstaxa",
        "text": "Avgiften för bygglov tas ut enligt kommunens taxa."},
    C: {"chunk_id": C, "kind": "local", "kommun": "Ydre", "title": "Avgifter", "header": "Ydre – Avgifter",
        "text": "Avgiften för bygglov för ett enbostadshus är 12 000 kr."},
}

HOUSE = "Bygglov is needed for a new house"
FEE = "The fee is 12 000 kr"
RAW = f"{HOUSE} [c:{A}]. {FEE} [c:{B}]."

HOUSE_SUPPORTED = {"text": HOUSE, "verdict": "supported", "chunk_ids": [A],
                   "supporting": [{"chunk_id": A, "sentence": "Bygglov krävs för nybyggnad av en byggnad."}]}
FEE_UNSUPPORTED = {"text": FEE, "verdict": "unsupported", "chunk_ids": [B], "supporting": []}
FEE_UNCITED = {"text": FEE, "verdict": "uncited", "chunk_ids": [], "supporting": []}


def get_chunk(chunk_id: str) -> dict | None:
    return CHUNKS.get(chunk_id)


class FakeJev:
    """The decision model, scripted: `supported` maps a claim's text to the probability that its sources state it
    (0 when absent), `needs_source` an uncited sentence's text to the probability that it needs a source (0 when
    absent), `place_backs` an uncited sentence's text to the probability that the pinned place's data backs it. The
    sentence choice picks the first sentence. `error` is raised on every call; `delay` (s) stalls each.
    `calls` holds every (state, questions) sent."""

    def __init__(self, supported=None, needs_source=None, place_backs=None, error: BaseException | None = None,
                 delay: float = 0.0):
        self.supported = supported or {}
        self.needs_source = needs_source or {}
        self.place_backs = place_backs or {}
        self.error, self.delay = error, delay
        self.calls: list[tuple] = []
        self._lock = threading.Lock()

    def __call__(self, state, questions, timeout_s: float = 20.0) -> dict:
        with self._lock:
            self.calls.append((state, questions))
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        if "supported" in questions:
            answers = {"supported": {"type": "noul", "noul": self.supported.get(state["claim"], 0.0)}}
            if "sentence" in questions:
                answers["sentence"] = {"type": "choice", "choice": next(iter(questions["sentence"]["criteria"]))}
            return answers
        def noul(name: str) -> float:
            text = state[f"sentence_{name.split('_')[1]}"]
            return (self.place_backs if name.startswith("place_") else self.needs_source).get(text, 0.0)
        return {name: {"type": "noul", "noul": noul(name)} for name in questions}

    def claims_asked(self) -> list[str]:
        """The cited claims put to the model, in no particular order."""
        return [state["claim"] for state, questions in self.calls if "supported" in questions]
