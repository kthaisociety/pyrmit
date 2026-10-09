"""
Chat integration of the agent (CHAT_MODE=agent): runs the agent in a thread and turns its
progress into the chat's SSE events and pipeline-inspector records.

    CHAT_MODE=agent            # default "rag"
    AGENT_MODEL=openai/gpt-6-luna
    AGENT_EFFORT=medium        # reasoning effort of the final (streamed) answer
    AGENT_EXPLORE_EFFORT=medium  # tool-calling turns (benchmark: low sees much less evidence; low = fast mode)
    AGENT_MAX_STEPS=10
"""

import os
import queue
import re
import threading
from typing import Callable, Generator

_tools = None
_lock = threading.Lock()


def agent_enabled() -> bool:
    return os.getenv("CHAT_MODE", "rag").strip().lower() == "agent"


def get_tools():
    from agentic.tools import CorpusTools
    from localrag.service import get_retriever

    global _tools
    with _lock:
        if _tools is None:
            _tools = CorpusTools(get_retriever())
            _tools.warm_up()
        return _tools


def source_label(chunk: dict) -> str:
    if chunk["kind"] == "law":
        return f"{chunk['title']}, {chunk['section']}"
    return f"{chunk.get('kommun')} – {chunk['title']}"


def chunk_row(chunk: dict) -> dict:
    from localrag.index import chunk_text

    return {"source": source_label(chunk), "chunk_index": chunk.get("chunk_index"), "distance": None,
            "url": chunk.get("url"), "content": chunk_text(chunk), "chunk_id": chunk["chunk_id"],
            "doc_id": chunk.get("doc_id"), "kind": chunk.get("kind")}


# Chunk ids are 16 hex characters; the model sometimes drops a few, so 8-15 are resolved by unique prefix
CITATION = re.compile(r"c:([0-9a-f]{8,16})(?![0-9a-f])")
GROUP = re.compile(r"\[([^\[\]]*)\]")
# Tails held back until the next delta: a citation still being streamed ("c", "c:", "c:3f0a...") or an
# unclosed bracket group (bounded, so a stray "[" cannot hold the stream for long)
PARTIAL_CITATION = re.compile(r"c(:[0-9a-f]{0,16})?$")
OPEN_GROUP = re.compile(r"\[[^\[\]]{0,300}$")


class CitationNumberer:
    """Turns "[c:<chunk_id>]" into "[n]" while the answer streams: sources are numbered in order of first
    citation, one number per source label (several chunks of one document share it). Repeats that this
    creates are merged: "[c:a; c:b]" -> "[1]", "[c:a] [c:b]" -> "[1]"."""

    def __init__(self, get_chunk: Callable[[str], dict | None]):
        self.get_chunk = get_chunk
        self.chunks: list[dict] = []
        self.labels: list[str] = []
        self.numbers: dict[str, int] = {}
        self.pending = ""
        self.previous: set[str] | None = None  # parts of the last citation group, while only spaces follow it
        self.eat_space = False  # a dropped group: remove one space from the text that follows it

    def _eat(self, text: str) -> str:
        if self.eat_space and text:
            self.eat_space = False
            return text[1:] if text.startswith(" ") else text
        return text

    def number(self, chunk_id: str) -> str:
        if chunk_id not in self.numbers:
            chunk = self.get_chunk(chunk_id)  # also resolves a truncated id by unique prefix
            if chunk is None:
                return "?"
            full_id = chunk["chunk_id"]
            if full_id not in self.numbers:
                label = source_label(chunk)
                if label not in self.labels:
                    self.labels.append(label)
                self.chunks.append(chunk)
                self.numbers[full_id] = self.labels.index(label) + 1
            self.numbers[chunk_id] = self.numbers[full_id]
        return str(self.numbers[chunk_id])

    def citations(self) -> list[dict]:
        """What each [n] stands for: its source label and the cited chunks (for the clickable citations)."""
        return [{"n": n, "label": label,
                 "chunks": [chunk_row(c) for c in self.chunks if self.numbers[c["chunk_id"]] == n]}
                for n, label in enumerate(self.labels, start=1)]

    def _convert(self, text: str) -> str:
        return CITATION.sub(lambda m: self.number(m.group(1)), text)

    def _render(self, text: str, final: bool) -> str:
        out, pos = [], 0
        for group in GROUP.finditer(text):
            between = text[pos:group.start()]
            pos = group.end()
            if not CITATION.search(group.group(1)):
                out.append(self._eat(self._convert(between)) + group.group(0))
                self.previous = None
                continue
            # "[c:a; PBL 9 kap. 3 §, 4 §]": split on ";" (and "," only between ids, not inside law references);
            # an id that matches no chunk (miscopied by the model) is dropped rather than shown as "?"
            pieces = []
            for piece in group.group(1).split(";"):
                pieces += piece.split(",") if CITATION.search(piece) else [piece]
            parts = [p for p in dict.fromkeys(self._convert(piece).strip() for piece in pieces) if p and p != "?"]
            if not parts:
                # The space before the group may already be streamed: eat the one after it instead
                out.append(self._eat(self._convert(between)))
                self.eat_space = True
                continue
            between = self._eat(between)
            if between.strip():
                self.previous = None
            if self.previous is not None and set(parts) <= self.previous:
                continue  # the same sources as the group just before: drop it and the spaces between
            out.append(self._convert(between) + "[" + "; ".join(parts) + "]")
            self.previous = set(parts)
        rest = text[pos:]
        if rest.strip():
            self.previous = None
        elif self.previous is not None and not final:
            self.pending = rest + self.pending  # spaces after a citation: wait to see if another one follows
            rest = ""
        out.append(self._eat(self._convert(rest)))
        return "".join(out)

    def feed(self, delta: str) -> str:
        text = self.pending + delta
        cut = len(text)
        for tail in (PARTIAL_CITATION.search(text), OPEN_GROUP.search(text)):
            if tail:
                cut = min(cut, tail.start())
        self.pending = text[cut:]
        return self._render(text[:cut], final=False)

    def close(self) -> str:
        text, self.pending = self.pending, ""
        return self._render(text, final=True)


def stream_agent(question: str, history: list[dict], record: Callable[..., None], sse: Callable[[dict], str],
                 flush: Callable[[], list[str]] = lambda: []) -> Generator[str, None, dict]:
    """Yield SSE strings while the agent works, including the final answer as it streams (citations
    already numbered); return {"answer", "law_rows", "local_rows", "sources", "citations", "run"}.

    `flush` returns the pipeline events of the calls recorded so far: streamed (and so saved with the
    message) as the agent goes, so someone reopening the chat mid-run sees its progress."""
    from agentic.agent import run_agent

    tools = get_tools()
    events: queue.Queue = queue.Queue()
    outcome: dict = {}

    def worker() -> None:
        try:
            outcome["run"] = run_agent(
                question, tools, history=history,
                effort=os.getenv("AGENT_EFFORT", "medium").strip(),
                explore_effort=os.getenv("AGENT_EXPLORE_EFFORT", "medium").strip() or None,
                max_steps=int(os.getenv("AGENT_MAX_STEPS", "10")),
                on_event=events.put,
            )
        except Exception as exc:
            outcome["error"] = exc
        finally:
            events.put(None)

    threading.Thread(target=worker, daemon=True).start()
    numberer = CitationNumberer(tools.get_chunk)
    answer = ""

    def delta(text: str) -> Generator[str, None, None]:
        nonlocal answer
        if text:
            answer += text
            yield sse({"type": "response.output_text.delta", "delta": text})

    while (event := events.get()) is not None:
        if event["type"] == "answer_delta":
            if not answer:
                yield sse({"type": "thinking", "label": "Writing the answer"})
            yield from delta(numberer.feed(event["delta"]))
        elif event["type"] in ("tool_call", "tool_result"):
            yield sse({key: event[key] for key in ("type", "name", "input", "result") if key in event})
        elif event["type"] == "llm_turn":
            record(kind="llm", name=f"Agent turn {event['turn']}", model=event.get("model"),
                   reasoning_effort=event.get("effort"), usage=event.get("usage"), duration_ms=event.get("ms"),
                   output=event.get("summary"))
            yield from flush()
        elif event["type"] == "tool_done":
            record(kind="tool", name=f"{event['name']}({event.get('input', '')[:80]})", input=event.get("input"),
                   output=event.get("output"), duration_ms=event.get("ms"), matches=event.get("chunks"))
            yield from flush()
    if "error" in outcome:
        raise outcome["error"]

    run = outcome["run"]
    if answer or numberer.pending:
        yield from delta(numberer.close())
    else:  # answered in an exploration turn (not streamed): send it whole
        yield from delta(numberer.feed(run.answer) + numberer.close())
    # Sources = cited chunks (falling back to everything the agent looked at), shown like the RAG retrieval
    chunks = numberer.chunks or [c for c in (tools.get_chunk(i) for i in run.seen_chunks) if c]
    law_rows = [chunk_row(c) for c in chunks if c["kind"] == "law"]
    local_rows = [chunk_row(c) for c in chunks if c["kind"] != "law"]
    return {"answer": answer, "law_rows": law_rows, "local_rows": local_rows, "sources": numberer.labels,
            "citations": numberer.citations(), "run": run}
