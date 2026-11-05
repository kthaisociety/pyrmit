"""
Agentic RAG: an LLM (GPT-6 Luna via OpenRouter by default) explores the local corpus with tools
(search, grep, list/read documents, exact law sections, PDF page images) and decides itself when
it has enough evidence to answer a feasibility question.

    python -m agentic.run "Can I build a 30 m2 guest house on my plot in Vallentuna?"
    python -m agentic.bench                  # case-study benchmark: agent vs. classic RAG
"""
