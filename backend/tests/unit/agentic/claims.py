"""
An answer, its chunks and a scripted model for tests of the claim check (agentic.claim_check) and the chat that runs it.

RAW cites A for the house rule and B for the fee; B does not state the fee, C (read by the agent, not cited) does.
"""

import json
import time
import types

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
REVISED = f"{HOUSE} [c:{A}]. {FEE} [c:{C}]."
SHORTENED = f"{HOUSE} [c:{A}]."

HOUSE_SUPPORTED = {"text": HOUSE, "verdict": "supported", "chunk_ids": [A],
                   "supporting": [{"chunk_id": A, "sentence": "Bygglov krävs för nybyggnad av en byggnad."}]}
FEE_UNSUPPORTED = {"text": FEE, "verdict": "unsupported", "chunk_ids": [B], "supporting": []}
FEE_UNCITED = {"text": FEE, "verdict": "uncited", "chunk_ids": [], "supporting": []}
FEE_SUPPORTED = {"text": FEE, "verdict": "supported", "chunk_ids": [C],
                 "supporting": [{"chunk_id": C, "sentence": "Avgiften för bygglov för ett enbostadshus är 12 000 kr."}]}
FEE_CITING_B = FEE_SUPPORTED | {"chunk_ids": [B]}


def judged(*claims: dict) -> str:
    """The judge's reply: JSON in the shape of the claims."""
    return json.dumps({"claims": list(claims)}, ensure_ascii=False)


def get_chunk(chunk_id: str) -> dict | None:
    return CHUNKS.get(chunk_id)


class FakeClient:
    """A Responses API client that answers with scripted replies, in order. A reply that is an exception is raised;
    a reply that is a float is a judge that stalls that many seconds, then finds no claims."""

    def __init__(self, replies: list):
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0) if self.replies else AssertionError("no more scripted replies")
        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, float):
            time.sleep(reply)
            reply = judged()
        return types.SimpleNamespace(output_text=reply, output=[], usage=None)

    def seen(self, call: int) -> str:
        """Everything sent to the model in one call, as text."""
        return json.dumps(self.calls[call], default=str, ensure_ascii=False)
