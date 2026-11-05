"""
Fill `query_sv_llm` in questions.jsonl with the Swedish query the chat's LLM actually
produces (same prompt as routers/chat.py with RETRIEVAL_BACKEND=local), so the eval does
not rely on hand-written Swedish queries that already know the corpus vocabulary.

    cd backend && python -m localrag.rewrite_queries          # one chat-model call per question
    python -m localrag.eval --query-field query_sv_llm
"""

import json

from agents.base import OPENAI_CHAT_MODEL
from corpus.common import read_jsonl
from llm import get_response_output_text, resolve_model_name
from localrag.eval import QUESTIONS_PATH
from localrag.service import SWEDISH_QUERY_SUFFIX, split_rewrite
from observability import create_chat_completion, get_openai_client


def main() -> None:
    questions = list(read_jsonl(QUESTIONS_PATH))
    client = get_openai_client()
    for question in questions:
        prompt = (
            "Translate the following user message to English (return only the translation, no explanation): "
            f"{question['question']}\n\n{SWEDISH_QUERY_SUFFIX}"
        )
        response = create_chat_completion(client, model=resolve_model_name(OPENAI_CHAT_MODEL), input=prompt,
                                          temperature=0)
        english, swedish = split_rewrite(get_response_output_text(response), question["question"])
        question["query_en_llm"], question["query_sv_llm"] = english, swedish
        print(f"[{question['id']}] {swedish}", flush=True)
    with QUESTIONS_PATH.open("w", encoding="utf-8") as file:
        for question in questions:
            file.write(json.dumps(question, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
