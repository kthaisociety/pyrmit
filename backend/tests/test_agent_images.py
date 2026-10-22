"""An image a tool returns goes with the next model call only, then is replaced by text (fake LLM and tools)."""

import json
from types import SimpleNamespace

import agentic.agent as agent
from agentic.tools import ToolResult


class FakeCall(SimpleNamespace):
    type = "function_call"

    def model_dump(self, exclude_none=True):
        return {"type": "function_call", "name": self.name, "arguments": self.arguments, "call_id": self.call_id}


class FakeClient:
    """Turn 1 views a page, turn 2 searches, turn 3 calls answer_ready, then the streamed answer."""

    def __init__(self):
        self.inputs = []
        self.responses = SimpleNamespace(create=self.create)
        self.turns = [
            [FakeCall(name="view_pdf_page", arguments=json.dumps({"doc_id": "pdf:0115:abc"}), call_id="1")],
            [FakeCall(name="search", arguments=json.dumps({"query": "nockhöjd"}), call_id="2")],
            [FakeCall(name="answer_ready", arguments=json.dumps({"mode": "verdict"}), call_id="3")],
        ]

    def create(self, input, stream=False, **kwargs):
        self.inputs.append(json.loads(json.dumps(input)))
        usage = SimpleNamespace(input_tokens=1, output_tokens=1, output_tokens_details=None, cost=0)
        if stream:
            return iter([SimpleNamespace(type="response.output_text.delta", delta="Answer."),
                         SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=usage))])
        return SimpleNamespace(output=self.turns.pop(0), output_text="", usage=usage)


def images_in(conversation: list) -> int:
    return sum(1 for item in conversation if isinstance(item.get("content"), list)
               for part in item["content"] if part.get("type") == "input_image")


def test_image_sent_once(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(agent, "get_openai_client", lambda: client)
    monkeypatch.setattr(agent, "run_tool", lambda tools, name, arguments: ToolResult(
        "Page 1/1 attached as an image.", image_png=b"png" if name == "view_pdf_page" else None))

    run = agent.run_agent("Får jag bygga?", tools=None, model="test/model", max_steps=5)

    assert run.answer == "Answer."
    # calls: turn 1 (no image yet), turn 2 (the image), turn 3 and the final answer (removed)
    assert [images_in(sent) for sent in client.inputs] == [0, 1, 0, 0]
    removed = [item for item in client.inputs[2] if item.get("role") == "user" and isinstance(item.get("content"), list)]
    assert agent.IMAGE_REMOVED.strip() in removed[0]["content"][0]["text"]
