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
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from agentic.tools import TOOL_SCHEMAS, CorpusTools, image_message, run_tool
from answer_language import LANGUAGE_RULE
from glossary import glossary_prompt
from llm import get_openai_client, resolve_model_name
from localrag.gazetteer import kommun_label

DEFAULT_MODEL = "openai/gpt-6-luna"

ROLE = """You are Pyrmit, an expert in Swedish land law and municipal planning (PBL, miljöbalken, jordabalken, fastighetsbildning, VA). Users (landowners, farmers, architects, developers, eco-village groups) ask in Swedish or English about building and land projects in Swedish kommuner: whether a defined project is feasible, how a rule or procedure works, where a project could go, or how to turn a project idea into something that can be approved. Be a constructive advisor: besides the limits, point out the options that the rules and the kommun's plans leave open."""

TOOLS_GUIDE = """You have tools over an offline corpus:
- Swedish statutes, one chunk per paragraph (§): PBL, PBF, MB, JB, FBL, BRL, anläggningslag, FMH (enskilt avlopp), LAV (vattentjänster), kulturmiljölag, ...
- The websites of all 290 kommuner (pages about bygglov, avlopp, taxor, planbesked, översiktsplan, detaljplaner) and PDFs linked from them (planbeskrivningar, plankartor, översiktsplaner, taxor). Coverage is uneven: a document may be missing.

How to work:
1. Identify the kommun and the place (find_kommun). Note what the corpus has for that kommun.
2. Work out which rules decide the case: is the site inside a detaljplan? national rules (bygglov/anmälan, förhandsbesked, strandskydd, jordbruksmark, sammanhållen bebyggelse, VA)? local rules (detaljplan provisions, översiktsplan intentions, local guidance, fees)?
3. For a site inside a detaljplan that no pinned place lists, list the kommun's plans (plans, with words of the area name) and read the plan's
   rules as a table (plan_rules: building area, heights, storeys, plot size, prickmark...); the plankarta shows
   which area carries which code: when the question names a property (e.g. "Grimsta 5:125") or a precise place, open
   the plankarta around it (view_map_area with the plankarta doc_id and the property number) and only apply the rules
   of the zone the property is in. Search in Swedish (search), use grep for exact terms (plan names, property designations, 'nockhöjd', 'byggnadsarea', amounts), read the promising chunks/documents fully (read), quote the exact statute sections (law_section). Look at a plankarta image only if the needed rule is spatial or the text is missing (view_pdf_page).
   search, grep and list_documents take doc_types (detaljplan, oversiktsplan, bygglov, strandskydd, avlopp, taxa,
   other) and title_contains to stay within some documents (e.g. the översiktsplan of a big kommun);
   grep(output='documents') shows which documents mention a term.
   The statutes are the current consolidated texts: PBL 9 kap. was renumbered by SFS 2025:974 (e.g. bygglov inside a
   detaljplan is now 9 kap. 56 §, outside 57 §, liten avvikelse 60-61 §, förhandsbesked 74 §; some sections have a
   second version in force from 2027-01-01). Do not rely on remembered section numbers: find provisions by searching
   their wording and cite the numbers shown in tool results.
4. Be fast: put every independent tool call of a step in the SAME turn (e.g. find_kommun + a law search + a kommun
   search together; several law_section calls together). Aim for 4-6 turns in total.
5. Local evidence decides most cases: before answer_ready, have read (read / list_documents + read) the kommun's most
   relevant document in full (the detaljplan, översiktsplan or guidance page for the place and topic) and grep'd the
   decisive exact terms (plan name, 'byggnadsarea', 'nockhöjd', 'förhandsbesked', ...).
6. As soon as the main points of the answer are supported by sources, call answer_ready (alone) with the kind of
   question (mode). Do not keep searching for marginal details; say what is unknown instead. You will then write the
   final answer."""

PIN_GUIDE = """What a pin on the map changes. A question is specific when it is about one place: it names an address, a property designation, a named plan or aktbeteckning, or says "here", "my plot", "our house" and the like. Any other question is a general question: how a rule, procedure, fee or document works, in Sweden or in a kommun as a whole.
- Specific, with a pin: the pinned place lists the plans that apply. Read their documents with read_plan first, without searching for them, and an amendment together with the plan it amends, as listed: it changes that plan where they differ. Answer from the passages, citing them, and search further only for what the plans do not settle, such as statute text.
- A plan listed as "Text not read": name the plan, say its text is not read, give the kommun's link listed with it and answer from the statutes.
- General, with a pin: answer generally, without bringing in the plan or the pinned place's other data.
- Specific, without a pin: your first call is ask_user with offer_pin, before any search: ask which place, and in the same card any other missing fact that would change the answer.
- General, without a pin: answer with the search tools and close with one sentence's offer to pin a place for an exact answer."""

ASK_GUIDE = """Asking instead of guessing (ask_user). Decide this first, before any search. A question is the user's own case when
it is about their property, building or project ("my plot", "my property", "my land", "my house", "our house", "I
want to build ...", "min tomt", "min fastighet", "mitt hus", "vårt hus", "vi vill bygga ..."), as opposed to a
general question about how a rule works. A permit or procedure question about their own property is their own case
too, in English as in Swedish: "Do I need a permit to build a pond on my land?", "How do I connect my house to the
municipal water?", "Can I merge my two properties?", "Do I need permission to put a gate in my wall?" all turn on
where the property is, so ask where it is (with offer_pin) before answering. In the user's own case the main
conclusion (allowed or not, permit needed or not, which route) turns on facts only they can give. Go through this
list: every fact on it that would change the conclusion and that the user has not given, in this message or earlier
in the conversation, you MUST ask for with ask_user (alone), all of them in one card (1-3 questions), instead of
answering:
- the place: nothing is pinned and the user has not named the kommun and the area; or the name they give exists in
  several kommuner (e.g. Kungsängen, Bergshamra, Ekeby): then ask which one, also when the question is general;
- the use: what the building or land will be used for (permanent home, holiday home, business and which kind,
  animals), when the rules differ by use;
- the measure: its size in m2, its height, or its distance to the boundary or the shoreline, whenever permit duty or
  legality depends on a threshold: sheds, garages, carports, extensions, decks (height above the ground), fences and
  plank (height), signs (size), wind turbines (height), anything near water (distance to the shore). Ask for the
  value itself as an open question ("How high above the ground will the deck be?"), never as yes/no about the
  threshold ("Is it within 100 metres?");
- what is to be built or done, when the user has not said ("can I build it?", "my project");
- which of two places or projects is meant.
- how many buildings or homes, when the user plans "a few" or "some": a single house and a group follow different
  routes.
In the user's own case an answer that lists "if X then A, if Y then B" is not a substitute for asking: ask. This
holds above all for the place. Whether they may repaint their house, dig a pond on their land, change the windows of
their house or pave their yard depends on the detaljplan and the area of their property, so the general rule is not
yet their answer: ask where it is (with offer_pin) instead of explaining the rule ("Får jag byta fönster på mitt
hus?" -> ask where the house is; "Vad gäller för fönsterbyten?" -> a general question, answer it).
Do not ask:
- on a general question (how a rule, procedure, fee, deadline or document works, what a kommun plans, "in general"):
  answer it, and say in one sentence what would change the answer for a specific case;
- for what you can find with the tools (which plan applies, a fee, a rule) or what the site is like once the place
  is known (whether the area has municipal water and sewage, strandskydd, what its plan allows): look it up first;
- whether the question is general or about their own case: decide that yourself from their words;
- for a more exact place when the conversation already names the kommun and the area, locality or plan area (e.g. "a
  villa plot in Kumla-Stensta, Vallentuna"): that is enough to find the rules, also with nothing pinned;
- for details that do not change the main conclusion: state them as assumptions in the answer;
- again for something the user already answered or declined to give ("just answer", "I'd rather not say"): answer
  generally or on stated assumptions.
Each question is short, asks for one fact, and is written in the language of the user's latest message (Swedish if
they wrote Swedish, otherwise English), as are its options. Give options only when a few answers cover most cases:
2-4 distinct, complete replies the user recognises and you can act on without more input (e.g. "A permanent home" /
"A holiday home", or "Use the pinned property, Fålhagen 61:11" / "Answer generally for Södermalm, Stockholm"; note
when a named place lies outside the kommun of the pin). A question with an open answer (a size, a height, an address,
what they plan to build) has no options. The card always adds a free-text field, so never write "Other", "Something
else", "Don't know", "Unsure" or "Please specify" as an option. To have them pin the place, set offer_pin as well as
asking for the place. Never list the kommuner of the corpus as options."""

# After the user answered the card the rule above made the agent ask again in plain text, ask_user being gone
# (41 of 99 follow-ups in the missing-info eval, 2026-11-12): a run that cannot ask gets this instead
ANSWERED_GUIDE = """Asking is over: the user has answered your questions (or declined to). Do not ask anything
more, in the text or otherwise, whatever other instructions say about asking. Research their question with the
tools as usual, using what they told you, and answer it in full in the mode's format; state as assumptions what
is still unknown."""

MODES = ("verdict", "explain", "propose", "develop", "off_topic")

MODES_GUIDE = """Kinds of questions (the mode of answer_ready; a question can mix them: pick the main one):
- verdict: a defined project at a known place: is it allowed, under which rules, how to get it approved?
- explain: how a rule, procedure, fee, deadline, map or document works; there is no project to judge.
- propose: the place is NOT fixed: the user asks where in a kommun a project could go (or what could be done with some
  land). This stays propose even when they also ask which approvals or studies it would take. Work fast from the
  översiktsplan: grep the kommun for its growth wording (e.g. 'utvecklingsområde|utbyggnadsområde|nya bostäder|
  prioriterade|serviceort|LIS'), read the 1-3 strongest passages (and its fördjupningar if listed), and note its limits
  (strandskydd, riksintressen, jordbruksmark, VA capacity). Propose places named in those documents, never invented
  ones, with what the documents say about each; do not research every place in depth (4-6 turns).
- develop: the place and the idea are given (roughly) and the user asks what is missing or how to make it work: find
  what could block it and the ways to make it work (another location or scale, phasing, the plan route: planbesked +
  detaljplan vs förhandsbesked + bygglov, liten avvikelse, dispens, shared facilities as a gemensamhetsanläggning),
  and what you need to know from the user.
- off_topic: the question is not about Swedish planning, building or land law (see the off-topic rule below).
""" + "\n" + ASK_GUIDE

OFF_TOPIC_GUIDE = """Off-topic questions. Some messages are not about Swedish planning, building or land law:
small talk and questions about Pyrmit itself ("hej", "tack", "what can you do?"), adjacent topics the corpus does not
cover (renovation tips, buying a house, insulation, interior design) and unrelated questions (a recipe, arithmetic,
code, general knowledge). Answer each of them. Your first call is answer_ready with mode "off_topic",
without any search or other tool, and you then write a short, direct answer from your own knowledge in the user's
language. Small talk and an adjacent question may end with at most one sentence on what Pyrmit helps with;
an unrelated question gets none.
A rule question the corpus may not cover (ROT-avdrag, electrical work, contracts, insurance) is different:
search the corpus first, and if it has nothing, give no answer in substance: say in the off_topic mode that the
question lies outside Pyrmit's sources and who can answer it (e.g. Skatteverket, an electrician).
A mixed question ("Behöver jag bygglov för en altan, och vilket trä håller längst?") is a planning question: answer it
in its own mode, with its sources, and give the off-topic part a short general answer at the end.
Never call ask_user for an off-topic question."""

ANSWER_FORMAT = """Answer in markdown, in the answer language (see the answer-language rule below), in the format of the mode you chose. The headings are given in English; a Swedish answer uses the Swedish headings in brackets:
- verdict:
  **Verdict:** [**Bedömning:**] one of Feasible / Feasible with conditions / Not feasible as described / Unclear [Genomförbart / Genomförbart med villkor / Inte genomförbart som beskrivet / Oklart], followed by one sentence.
  **Key rules and constraints:** [**Regler och begränsningar:**] bullets.
  **Process and next steps:** [**Process och nästa steg:**] permits/notifications needed, who to contact at the kommun, fees and processing times when found.
  **Uncertainties:** [**Osäkerheter:**] what the corpus did not show and what the user must check (e.g. the exact detaljplan for their property).
- explain:
  **Answer:** [**Svar:**] two or three sentences.
  **How it works:** [**Så fungerar det:**] numbered steps or bullets, each with its rule or document.
  **In <kommun>:** [**I <kommun>:**] local specifics (pages, fees, processing times, contacts), when the question names a kommun.
  **Uncertainties:** [**Osäkerheter:**] as above.
- propose:
  **Options:** [**Alternativ:**] 2-4 options, each a short paragraph: the place as the documents name it, what could be built there, why
  it fits (what the plan says), its main constraints, and the first step (planbesked, förhandsbesked, bygglov).
  **What decides between them:** [**Vad som avgör mellan dem:**] the constraints and choices that matter most.
  **Questions for you:** [**Frågor till dig:**] what would narrow the options.
  **Uncertainties:** [**Osäkerheter:**] as above.
- develop:
  **Your project as understood:** [**Ditt projekt som vi förstår det:**] one or two sentences.
  **What could block it:** [**Vad som kan stoppa det:**] bullets, each with its rule.
  **Ways to make it work:** [**Sätt att få det att fungera:**] concrete options (location, scale, plan route, shared facilities, phasing), each with the
  rule or plan statement that allows it.
  **Suggested path:** [**Föreslagen väg:**] ordered next steps.
  **Questions for you:** [**Frågor till dig:**] the missing facts that change the answer.
  **Uncertainties:** [**Osäkerheter:**] as above.
- off_topic: a short, plain answer of a few sentences: no headings, no citations, no **Verdict:** line.
In explain / propose / develop, add a **Verdict:** [**Bedömning:**] line only if the user asks whether something is allowed.
Citations: name the law reference (e.g. PBL 9 kap. 4 §) or document in the sentence, and put the source id right after the claim as [c:<chunk_id>] (several: [c:<id>; c:<id>]). Copy ids exactly (16 characters) and never nest brackets: write "PBL 9 kap. 4 § allows … [c:<id>]", not "[PBL 9 kap. 4 § [c:<id>]]". Quote decisive Swedish wording verbatim, as the answer-language rule says.
Grounding rules (all modes but off_topic): every rule, number, fee, deadline or document fact must carry the [c:<chunk_id>] of a tool result
that states it (tool results show these ids). If you did not read it in a tool result, do not state it, or say it
must be checked.
Completeness: the user will act on this answer, so before writing go through your tool results and include every rule, condition, procedural step, fee, deadline and site constraint (strandskydd, farmland, flood, noise, risk, VA, heritage...) that bears on the question, each with its source; an adviser flags a constraint rather than omits it. Be complete on what the sources say and silent on what they do not."""
# "Completeness" replaced "prefer fewer, well-sourced points" on 2026-10-21: the agent left facts it had read out of
# its answer; +0.03 / +0.05 key points (MiMo / Luna judge) on the 52 dev cases, same latency and cost (benchmark
# report 2.9, with the rejected variants: per-mode recipes + site checklist, MiMo Flash as the agent)

# Repeated where the answer is written: after many Swedish tool results the model drifted into Swedish for English
# questions (live run, 2026-11-07). It names no language: the model still decides it (ADR-0011)
ANSWER_LANGUAGE_REMINDER = ("Write it in the user's language as the answer-language rule says: Swedish if they wrote "
                            "Swedish, otherwise English, whatever the language of the sources.")

# After Swedish tool results the model wrote its question card in Swedish for an English question (missing-info eval,
# 2026-11-12): the same drift as in answers, so the same reminder follows each turn's tool results while it can ask
ASK_LANGUAGE_REMINDER = ("(If you ask the user instead of answering, write the questions and options in the language "
                         "of their latest message, whatever the language of these sources.)")

IMAGE_REMOVED = "\n(Image removed after the turn it was shown in: use what you noted from it.)"

SYSTEM_PROMPT = (f"{ROLE}\n\n{TOOLS_GUIDE}\n\n{PIN_GUIDE}\n\n{MODES_GUIDE}\n\n{OFF_TOPIC_GUIDE}\n\n{ANSWER_FORMAT}\n\n{LANGUAGE_RULE}\n\n"
                 f"{glossary_prompt()}")

# The corpus line of TOOLS_GUIDE about the kommuner: true of the national corpus only. On a snapshot (data/small's
# few kommuner, the Neon demo's three) the agent answered "all 290 kommuner" from it; kommun_scope replaces it
NATIONAL_SCOPE = ("- The websites of all 290 kommuner (pages about bygglov, avlopp, taxor, planbesked, översiktsplan, "
                  "detaljplaner) and PDFs linked from them (planbeskrivningar, plankartor, översiktsplaner, taxor). "
                  "Coverage is uneven: a document may be missing.")
assert NATIONAL_SCOPE in TOOLS_GUIDE


def kommun_scope(tools: CorpusTools) -> str:
    """NATIONAL_SCOPE when the corpus holds (almost) every kommun, else the kommuner it does hold."""
    codes = tools.corpus_kommuner() if hasattr(tools, "corpus_kommuner") else None  # tests run without tools
    if codes is None or len(codes) >= 250:
        return NATIONAL_SCOPE
    return (f"- The websites of {len(codes)} kommuner only: {', '.join(kommun_label(code) for code in codes)} (pages "
            "about bygglov, avlopp, taxor, planbesked, översiktsplan, detaljplaner, and the PDFs linked from them). "
            "This corpus has no document of any other kommun: say so when asked about one (the statutes apply "
            "everywhere).")


@dataclass
class AskedQuestion:
    """One question of the agent's question card (ask_user), for a fact only the user knows that would change the
    answer.

    `question` is one short question in the answer language, never empty. `options` holds 0 to MAX_CHOICES complete
    replies the user can click and the agent can act on without more input, trimmed, without empties or repeats; it
    is empty for an open question, where a few likely answers do not exist (the agent decides). Every question also
    gets a free-text "Other" field in the card, so the options never include "other" or "please provide ...".
    """
    question: str
    options: list[str] = field(default_factory=list)


MAX_QUESTIONS = 3  # questions in one card: every fact that would change the answer is asked for in one round


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
    mode: str | None = None  # kind of question the agent chose in answer_ready (MODES)
    # ask_user: the question card, 1 to MAX_QUESTIONS questions in the order asked (empty when the agent answered).
    # `answer` then lists every question as text, so the saved message reads on its own.
    questions: list[AskedQuestion] = field(default_factory=list)
    offer_pin: bool = False  # ask_user: the card also offers to pin the place on the map
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
    "parameters": {"type": "object", "properties": {
        "mode": {"type": "string", "enum": list(MODES), "description": "kind of question, sets the answer format"},
    }, "required": ["mode"]},
}


MAX_CHOICES = 4
ASK_USER_TOOL = {
    "type": "function", "name": "ask_user",
    "description": "Call (alone) instead of answering when the main conclusion turns on facts only the user can give "
                   "and has not given. Ask for all of them at once: the questions are shown together in one card, each "
                   "with its options as buttons and a free-text field.",
    "parameters": {"type": "object", "properties": {
        "questions": {"type": "array", "minItems": 1, "maxItems": MAX_QUESTIONS, "items": {
            "type": "object", "properties": {
                "question": {"type": "string", "description": "one short question for one fact, in the "
                                                                 "language of the user's latest message "
                                                                 "(English for an English message, even "
                                                                 "after reading Swedish sources)"},
                "options": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_CHOICES,
                            "description": "2-4 complete replies the user can click and you can act on without more "
                                           "input, only when a few answers cover most cases; [] for an open question. "
                                           "Never 'Other' or 'please specify': a free-text field is always added"},
            }, "required": ["question", "options"]},
            "description": "1-3 questions, one per missing fact"},
        "offer_pin": {"type": "boolean", "description": "also show a button that opens the map to pin the place"},
    }, "required": ["questions"]},
}


def _clean_options(options) -> list[str]:
    """Options trimmed, without empties or repeats, at most MAX_CHOICES."""
    if not isinstance(options, list):
        return []
    trimmed = [str(option).strip() for option in options if isinstance(option, (str, int, float))]
    return list(dict.fromkeys(option for option in trimmed if option))[:MAX_CHOICES]


def _questions(arguments: str | None) -> tuple[list[AskedQuestion], bool]:
    """(questions, offer_pin) of an ask_user call: questions without text dropped, at most MAX_QUESTIONS, repeats
    merged. The flat form of a single question ({"question", "options"}) is read as one question."""
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    items = parsed.get("questions")
    if not isinstance(items, list):
        items = [parsed] if "question" in parsed else []
    questions: list[AskedQuestion] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question") or "").strip()
        if text and all(text != asked.question for asked in questions):
            questions.append(AskedQuestion(text, _clean_options(item.get("options"))))
    return questions[:MAX_QUESTIONS], bool(parsed.get("offer_pin"))


def questions_text(questions: list[AskedQuestion]) -> str:
    """The card as the reply's text, for the saved conversation: the question, or one question per line."""
    return "\n".join(asked.question for asked in questions)


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
              on_event: Callable[[dict], None] | None = None, disabled_tools: set[str] | None = None,
              allow_ask: bool = True) -> AgentRun:
    """`effort` for the final answer, `explore_effort` for the tool-calling turns (None: same as `effort`).
    `disabled_tools` removes tools for a run (benchmark ablations, e.g. no map reading); `allow_ask=False` leaves
    ask_user out (the message answers the agent's own question)."""
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
    schemas = ([schema for schema in TOOL_SCHEMAS if schema["name"] not in disabled] + [ANSWER_READY_TOOL]
               + ([ASK_USER_TOOL] if allow_ask else []))
    note = f"\n\nNot available in this session: {', '.join(sorted(disabled))}." if disabled else ""
    instructions = SYSTEM_PROMPT.replace(NATIONAL_SCOPE, kommun_scope(tools)) + note
    if not allow_ask:
        instructions = instructions.replace(ASK_GUIDE, ANSWERED_GUIDE)
    # An image goes with the next model call only (re-sending every image each turn multiplied the input tokens):
    # `fresh` = attached, not sent yet; `shown` = sent once, replaced by text before the following call
    fresh: list[int] = []
    shown: list[int] = []

    def send_images_once() -> None:
        for index in shown:
            text = conversation[index]["content"][0]["text"]
            conversation[index] = {"role": "user", "content": [{"type": "input_text", "text": text + IMAGE_REMOVED}]}
        shown[:] = fresh
        fresh.clear()

    def turn_event(step: int, turn_effort: str, response, turn_started: float, summary: str) -> None:
        turn_usage: dict = {}
        _usage_dict(turn_usage, response.usage)
        emit({"type": "llm_turn", "turn": step, "model": model, "effort": turn_effort, "usage": turn_usage,
              "ms": round((time.perf_counter() - turn_started) * 1000), "summary": summary})

    for step in range(1, max_steps + 1):
        turn_started = time.perf_counter()
        last = step == max_steps
        if last:  # budget spent: the last turn only picks the mode, so the answer still gets its format
            conversation.append({"role": "user", "content": "Tool budget reached: call answer_ready now with the "
                                                            "mode of the question."})
        send_images_once()
        response = client.responses.create(
            model=model, instructions=instructions, input=conversation,
            tools=[ANSWER_READY_TOOL] if last else schemas, reasoning={"effort": explore_effort},
            **({"tool_choice": "required"} if last else {}),
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
        asked = next((c for c in calls if c.name == "ask_user"), None)
        if asked:  # a question card for the user is the reply: no tools, no final answer turn
            questions, offer_pin = _questions(asked.arguments)
            if questions:
                run.answer, run.questions, run.offer_pin = questions_text(questions), questions, offer_pin
                break
            conversation.append({"type": "function_call_output", "call_id": asked.call_id,
                                 "output": "ask_user needs at least one question: answer instead, or ask again."})
        ready = [c for c in calls if c.name == "answer_ready"]
        for call in ready:
            try:
                mode = json.loads(call.arguments or "{}").get("mode")
            except json.JSONDecodeError:
                mode = None
            run.mode = mode if mode in MODES else None
            fmt = f"the {run.mode} format" if run.mode else "the required format"
            conversation.append({"type": "function_call_output", "call_id": call.call_id,
                                 "output": f"Write the final answer now, in {fmt}. {ANSWER_LANGUAGE_REMINDER}"})
            asked_for_answer = True
        work = [c for c in calls if c.name not in ("answer_ready", "ask_user")]
        for call in work:
            emit({"type": "tool_call", "name": call.name, "input": call.arguments or "{}"})
        # Independent calls of one turn run in parallel (DB reads, GPU search, PDF rendering)
        for call, arguments, result, ms in pool.map(lambda c: _run_call(tools, c), work):
            run.seen_chunks.extend(chunk_id for chunk_id in result.chunk_ids if chunk_id not in run.seen_chunks)
            reminder = f"\n\n{ASK_LANGUAGE_REMINDER}" if allow_ask and call is work[-1] else ""
            conversation.append({"type": "function_call_output", "call_id": call.call_id,
                                 "output": result.text + reminder})
            if result.image_png:
                fresh.append(len(conversation))
                conversation.append(image_message(result))
            run.steps.append({"tool": call.name, "arguments": arguments, "chunks": result.chunk_ids,
                              "output_chars": len(result.text), "image": bool(result.image_png), "ms": ms, "turn": step,
                              "error": result.error})
            emit({"type": "tool_result", "name": call.name, "result": result.text[:300],
                  "chunks": len(result.chunk_ids), "ms": ms, "error": result.error})
            emit({"type": "tool_done", "name": call.name, "input": json.dumps(arguments, ensure_ascii=False),
                  "output": result.text[:4000], "chunks": len(result.chunk_ids), "chunk_ids": result.chunk_ids, "ms": ms,
                  "image": bool(result.image_png)})
        if ready:
            break
    pool.shutdown(wait=False)

    if not run.answer:
        # The final answer, streamed: the only turn that uses the answer effort
        if not asked_for_answer:
            conversation.append({"role": "user", "content": "Tool budget reached: answer now with the evidence you have, "
                                                            f"in the required format. {ANSWER_LANGUAGE_REMINDER}"})
        turn_started = time.perf_counter()
        send_images_once()
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
