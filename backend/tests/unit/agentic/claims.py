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
EARLIER = "Detaljplanen gäller sedan länge"
TWO_SENTENCES = f"{EARLIER}. {HOUSE} [c:{A}]."  # one stretch, or two when cut per sentence

HOUSE_SUPPORTED = {"text": HOUSE, "verdict": "supported", "chunk_ids": [A],
                   "supporting": [{"chunk_id": A, "sentence": "Bygglov krävs för nybyggnad av en byggnad."}],
                   "level": None, "unbacked": []}
FEE_UNSUPPORTED = {"text": FEE, "verdict": "unsupported", "chunk_ids": [B], "supporting": [], "level": None,
                   "unbacked": []}
FEE_UNCITED = {"text": FEE, "verdict": "uncited", "chunk_ids": [], "supporting": [], "level": None, "unbacked": []}


def get_chunk(chunk_id: str) -> dict | None:
    return CHUNKS.get(chunk_id)


class FakeJev:
    """The decision model, scripted: `supported` maps a claim's text to the probability that its sources state it
    (0 when absent), `needs_source` an uncited sentence's text to the probability that it needs a source (0 when
    absent), `place_backs` an uncited sentence's text to the probability that the pinned place's data backs it,
    `hedge` a claim's or sentence's text to the probability that it is a hedge (a "hedge" question in a claim's call,
    "hedge_<i>" in the uncited sentences' call; 0 when absent). For a claim's call also: `addition` maps a claim's text
    to the probability that it says something its sources do not state (an "addition" question; 0 when absent), `fact`
    to the probability that it states a fact (a "fact" question; 1 when absent) and `part` to the probability that
    its sources state at least part of it (a "part" question; 0 when absent). The
    sentence choice picks the first sentence. `error` is raised on every call, and a RuntimeError on the call
    about the claim `fail_on`; `delay` (s) stalls each.
    `calls` holds every (state, questions) sent."""

    def __init__(self, supported=None, needs_source=None, place_backs=None, hedge=None,
                 error: BaseException | None = None, delay: float = 0.0, fail_on: str | None = None,
                 addition=None, fact=None, part=None):
        self.supported = supported or {}
        self.hedge = hedge or {}
        self.addition, self.fact, self.part = addition or {}, fact or {}, part or {}
        self.needs_source = needs_source or {}
        self.place_backs = place_backs or {}
        self.fail_on = fail_on
        self.error, self.delay = error, delay
        self.calls: list[tuple] = []
        self._lock = threading.Lock()

    def __call__(self, state, questions, timeout_s: float = 20.0) -> dict:
        with self._lock:
            self.calls.append((state, questions))
        if self.delay:
            time.sleep(self.delay)
        if self.error or (self.fail_on is not None and state.get("claim") == self.fail_on):
            raise self.error or RuntimeError("one call failed")
        if "claim" in state:
            answers = {}
            if "supported" in questions:
                answers["supported"] = {"type": "noul", "noul": self.supported.get(state["claim"], 0.0)}
            if "sentence" in questions:
                answers["sentence"] = {"type": "choice", "choice": next(iter(questions["sentence"]["criteria"]))}
            if "hedge" in questions:
                answers["hedge"] = {"type": "noul", "noul": self.hedge.get(state["claim"], 0.0)}
            for name, script, absent in (("addition", self.addition, 0.0), ("fact", self.fact, 1.0),
                                         ("part", self.part, 0.0)):
                if name in questions:
                    answers[name] = {"type": "noul", "noul": script.get(state["claim"], absent)}
            return answers
        def noul(name: str) -> float:
            text = state[f"sentence_{name.split('_')[1]}"]
            script = {"place": self.place_backs, "hedge": self.hedge}.get(name.split("_")[0], self.needs_source)
            return script.get(text, 0.0)
        return {name: {"type": "noul", "noul": noul(name)} for name in questions}

    def claims_asked(self) -> list[str]:
        """The cited claims put to the model, in no particular order."""
        return [state["claim"] for state, questions in self.calls if "supported" in questions]
