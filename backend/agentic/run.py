"""
Ask the agent one question from the command line.

    cd backend
    LLM_PROVIDER=openrouter python -m agentic.run "Can I build a guest house on my plot in Vallentuna?"
    python -m agentic.run --kommuner 0115 --effort medium "..."   # smaller corpus = less RAM
"""

import argparse
import os

from agentic.agent import run_agent
from agentic.tools import CorpusTools
from localrag.index import VectorStore, load_chunks
from localrag.retriever import LocalRetriever


def build_tools(kommuner: list[str] | None = None, model: str = "st-arctic-l-v2") -> CorpusTools:
    indexed = VectorStore(model).position
    chunks = [chunk for chunk in load_chunks(kommuner) if chunk["chunk_id"] in indexed]
    tools = CorpusTools(LocalRetriever(chunks, model=model, bm25_modes=("stem",)))
    tools.warm_up()
    return tools


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the corpus agent on one question")
    parser.add_argument("question")
    parser.add_argument("--kommuner", nargs="*", help="restrict the corpus to laws + these kommun codes")
    parser.add_argument("--effort", default="medium", help="final answer effort")
    parser.add_argument("--explore-effort", default="low", help="effort of the tool-calling turns")
    parser.add_argument("--max-steps", type=int, default=10)
    args = parser.parse_args()
    os.environ.setdefault("LLM_PROVIDER", "openrouter")

    tools = build_tools(args.kommuner)
    def show(event: dict) -> None:
        if event["type"] in ("tool_call", "tool_result"):
            print(f"  {event['type']:<11} {event['name']}: {(event.get('input') or event.get('result', ''))[:160]}")
        elif event["type"] == "llm_turn":
            print(f"  -- turn {event['turn']} ({event['effort']}, {event['ms'] / 1000:.1f}s): {event['summary'][:120]}")

    run = run_agent(args.question, tools, effort=args.effort, explore_effort=args.explore_effort,
                    max_steps=args.max_steps, on_event=show)
    print("\n" + run.answer)
    print(f"\n{len(run.steps)} tool calls, {run.llm_calls} LLM calls, {run.seconds}s "
          f"(first answer token {run.first_token_s}s), "
          f"{run.usage['input_tokens']} in / {run.usage['output_tokens']} out tokens, ${run.usage['cost']:.4f}")


if __name__ == "__main__":
    main()
