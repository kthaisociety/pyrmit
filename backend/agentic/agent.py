"""
Tool-calling agent over the local corpus (OpenAI Responses API, through OpenRouter by default).

The model plans, calls tools (several per turn, run in parallel), reads what it needs and calls
`answer_ready` when the evidence is sufficient. Latency is almost all model turns, so the exploration
turns use a low reasoning effort and only the final answer uses the answer effort; the final answer is
streamed (on_event "answer_delta"). A step budget forces the answer.
"""

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from agentic.tools import TOOL_SCHEMAS, CorpusTools, image_message, run_tool
from llm import get_openai_client, resolve_model_name

DEFAULT_MODEL = "openai/gpt-6-luna"

ROLE = """You are Pyrmit, an expert in Swedish land law and municipal planning (PBL, miljöbalken, jordabalken, fastighetsbildning, VA). Users (landowners, architects, developers, eco-village projects) ask in English whether a building project is feasible in a given Swedish kommun, and how to get it approved."""

TOOLS_GUIDE = """You have tools over an offline corpus:
- Swedish statutes, one chunk per paragraph (§): PBL, PBF, MB, JB, FBL, BRL, anläggningslag, FMH (enskilt avlopp), LAV (vattentjänster), kulturmiljölag, ...
- The websites of all 290 kommuner (pages about bygglov, avlopp, taxor, planbesked, översiktsplan, detaljplaner) and PDFs linked from them (planbeskrivningar, plankartor, översiktsplaner, taxor). Coverage is uneven: a document may be missing.

How to work:
1. Identify the kommun and the place (find_kommun). Note what the corpus has for that kommun.
2. Work out which rules decide the case: is the site inside a detaljplan? national rules (bygglov/anmälan, förhandsbesked, strandskydd, jordbruksmark, sammanhållen bebyggelse, VA)? local rules (detaljplan provisions, översiktsplan intentions, local guidance, fees)?
3. For a site inside a detaljplan, list the kommun's plans (plans, with words of the area name) and read the plan's
   rules as a table (plan_rules: building area, heights, storeys, plot size, prickmark...); the plankarta shows
   which area carries which code: when the question names a property (e.g. "Grimsta 5:125") or a precise place, open
   the plankarta around it (view_map_area with the plankarta doc_id and the property number) and only apply the rules
   of the zone the property is in. Search in Swedish (search), use grep for exact terms (plan names, property designations, 'nockhöjd', 'byggnadsarea', amounts), read the promising chunks/documents fully (read), quote the exact statute sections (law_section). Look at a plankarta image only if the needed rule is spatial or the text is missing (view_pdf_page).
   The statutes are the current consolidated texts: PBL 9 kap. was renumbered by SFS 2025:974 (e.g. bygglov inside a
   detaljplan is now 9 kap. 56 §, outside 57 §, liten avvikelse 60-61 §, förhandsbesked 74 §; some sections have a
   second version in force from 2027-01-01). Do not rely on remembered section numbers: find provisions by searching
   their wording and cite the numbers shown in tool results.
4. Be fast: put every independent tool call of a step in the SAME turn (e.g. find_kommun + a law search + a kommun
   search together; several law_section calls together). Aim for 4-6 turns in total.
5. Local evidence decides most cases: before answer_ready, have read (read / list_documents + read) the kommun's most
   relevant document in full (the detaljplan, översiktsplan or guidance page for the place and topic) and grep'd the
   decisive exact terms (plan name, 'byggnadsarea', 'nockhöjd', 'förhandsbesked', ...).
6. As soon as the verdict and the main constraints are supported by sources, call answer_ready (alone). Do not keep
   searching for marginal details; say what is unknown instead. You will then write the final answer."""

ANSWER_FORMAT = """Answer in English, in markdown:
**Verdict:** one of Feasible / Feasible with conditions / Not feasible as described / Unclear, followed by one sentence.
**Key rules and constraints:** bullets; name the law reference (e.g. PBL 9 kap. 4 §) or document in the sentence, and put the source id right after the claim as [c:<chunk_id>] (several: [c:<id>; c:<id>]). Copy ids exactly (16 characters) and never nest brackets: write "PBL 9 kap. 4 § allows … [c:<id>]", not "[PBL 9 kap. 4 § [c:<id>]]". Quote decisive Swedish wording briefly with an English gloss.
**Process and next steps:** permits/notifications needed, who to contact at the kommun, fees and processing times when found.
**Uncertainties:** what the corpus did not show and what the user must check (e.g. the exact detaljplan for their property).
Grounding rules: every rule, number, fee, deadline or document fact must carry the [c:<chunk_id>] of a tool result
that states it (tool results show these ids). If you did not read it in a tool result, do not state it, or say it
must be checked. Prefer fewer, well-sourced points over many unsourced details."""

SYSTEM_PROMPT = f"{ROLE}\n\n{TOOLS_GUIDE}\n\n{ANSWER_FORMAT}"


@dataclass
class AgentRun:
    answer: str = ""
    steps: list[dict] = field(default_factory=list)       # one entry per tool call
    seen_chunks: list[str] = field(default_factory=list)  # every chunk id a tool showed
    cited_chunks: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0, "cost": 0.0})
    llm_calls: int = 0
    seconds: float = 0.0
    first_token_s: float | None = None  # time until the first answer token (streamed answer)
    error: str | None = None


def _add_usage(total: dict, usage) -> None:
    if usage is None:
        return
    total["input_tokens"] += getattr(usage, "input_tokens", 0) or 0
    total["output_tokens"] += getattr(usage, "output_tokens", 0) or 0
    details = getattr(usage, "output_tokens_details", None)
    total["reasoning_tokens"] += getattr(details, "reasoning_tokens", 0) or 0
    total["cost"] += float(getattr(usage, "cost", 0) or 0)


def _usage_dict(target: dict, usage) -> None:
    target.update({"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0, "cost": 0.0})
    _add_usage(target, usage)
    target["total_tokens"] = target["input_tokens"] + target["output_tokens"]


ANSWER_READY_TOOL = {
    "type": "function", "name": "answer_ready",
    "description": "Call (alone) when you have enough evidence; you will then be asked for the final answer.",
    "parameters": {"type": "object", "properties": {}},
}


def _run_call(tools: CorpusTools, call) -> tuple:
    try:
        arguments = json.loads(call.arguments or "{}")
    except json.JSONDecodeError:
        arguments = {}
    started = time.perf_counter()
    result = run_tool(tools, call.name, arguments)
    return call, arguments, result, round((time.perf_counter() - started) * 1000)


def run_agent(question: str, tools: CorpusTools, history: list[dict] | None = None, model: str | None = None,
              effort: str = "medium", explore_effort: str | None = "low", max_steps: int = 10,
              on_event: Callable[[dict], None] | None = None, disabled_tools: set[str] | None = None) -> AgentRun:
    """`effort` for the final answer, `explore_effort` for the tool-calling turns (None: same as `effort`).
    `disabled_tools` removes tools for a run (benchmark ablations, e.g. no map reading)."""
    client = get_openai_client()
    model = resolve_model_name(model or os.getenv("AGENT_MODEL", DEFAULT_MODEL))
    explore_effort = explore_effort or effort
    emit = on_event or (lambda event: None)
    run = AgentRun()
    started = time.perf_counter()
    conversation: list = list(history or []) + [{"role": "user", "content": question}]
    pool = ThreadPoolExecutor(max_workers=6)
    asked_for_answer = False
    disabled = set(disabled_tools or ())
    schemas = [schema for schema in TOOL_SCHEMAS if schema["name"] not in disabled] + [ANSWER_READY_TOOL]
    note = f"\n\nNot available in this session: {', '.join(sorted(disabled))}." if disabled else ""
    instructions = SYSTEM_PROMPT + note

    def turn_event(step: int, turn_effort: str, response, turn_started: float, summary: str) -> None:
        turn_usage: dict = {}
        _usage_dict(turn_usage, response.usage)
        emit({"type": "llm_turn", "turn": step, "model": model, "effort": turn_effort, "usage": turn_usage,
              "ms": round((time.perf_counter() - turn_started) * 1000), "summary": summary})

    for step in range(1, max_steps + 1):
        turn_started = time.perf_counter()
        response = client.responses.create(
            model=model, instructions=instructions, input=conversation,
            tools=schemas, reasoning={"effort": explore_effort},
        )
        run.llm_calls += 1
        _add_usage(run.usage, response.usage)
        calls = [item for item in response.output if item.type == "function_call"]
        turn_event(step, explore_effort, response, turn_started,
                   ", ".join(f"{c.name}({c.arguments})" for c in calls) or "answered directly")
        conversation.extend(item.model_dump(exclude_none=True) for item in response.output)
        if not calls:  # answered without calling answer_ready: keep it
            run.answer = response.output_text or ""
            break
        ready = [c for c in calls if c.name == "answer_ready"]
        for call in ready:
            conversation.append({"type": "function_call_output", "call_id": call.call_id,
                                 "output": "Write the final answer now, in the required format."})
            asked_for_answer = True
        work = [c for c in calls if c.name != "answer_ready"]
        for call in work:
            emit({"type": "tool_call", "name": call.name, "input": call.arguments or "{}"})
        # Independent calls of one turn run in parallel (DB reads, GPU search, PDF rendering)
        for call, arguments, result, ms in pool.map(lambda c: _run_call(tools, c), work):
            run.seen_chunks.extend(chunk_id for chunk_id in result.chunk_ids if chunk_id not in run.seen_chunks)
            conversation.append({"type": "function_call_output", "call_id": call.call_id, "output": result.text})
            if result.image_png:
                conversation.append(image_message(result))
            run.steps.append({"tool": call.name, "arguments": arguments, "chunks": result.chunk_ids,
                              "output_chars": len(result.text), "image": bool(result.image_png), "ms": ms, "turn": step})
            emit({"type": "tool_result", "name": call.name, "result": result.text[:300]})
            emit({"type": "tool_done", "name": call.name, "input": json.dumps(arguments, ensure_ascii=False),
                  "output": result.text[:4000], "chunks": len(result.chunk_ids), "ms": ms})
        if ready:
            break
    pool.shutdown(wait=False)

    if not run.answer:
        # The final answer, streamed: the only turn that uses the answer effort
        if not asked_for_answer:
            conversation.append({"role": "user", "content": "Tool budget reached: answer now with the evidence you "
                                                            "have, in the required format."})
        turn_started = time.perf_counter()
        stream = client.responses.create(model=model, instructions=instructions, input=conversation,
                                         reasoning={"effort": effort}, stream=True)
        parts, final = [], None
        for event in stream:
            if event.type == "response.output_text.delta" and event.delta:
                if not parts:
                    run.first_token_s = round(time.perf_counter() - started, 1)
                parts.append(event.delta)
                emit({"type": "answer_delta", "delta": event.delta})
            elif event.type == "response.completed":
                final = event.response
        run.answer = "".join(parts)
        run.llm_calls += 1
        if final is not None:
            _add_usage(run.usage, final.usage)
            turn_event(run.llm_calls, effort, final, turn_started, "final answer")

    # Every "c:<id>", also inside grouped citations like "[c:<id>; c:<id>]" or "[PBL 9 kap. 4 §; c:<id>]"
    run.cited_chunks = list(dict.fromkeys(re.findall(r"c:([0-9a-f]{8,16})(?![0-9a-f])", run.answer)))
    run.seconds = round(time.perf_counter() - started, 1)
    return run
