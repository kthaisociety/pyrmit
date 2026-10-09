"""
Find which kommun a question is about: kommun names (incl. genitive "Vallentunas") and
localities from Wikidata ("Lindholmen" -> Vallentuna). Names that are also common words
("Mark", "Ale", "Sala") or short names only match when capitalised. Places missing from
Wikidata are looked up in the corpus itself (CorpusPlaces).
"""

import json
import re
from collections import Counter, defaultdict
from functools import lru_cache

from corpus.common import MUNICIPALITIES_PATH
from localrag.analyzer import SWEDISH_STOPWORDS

_COMMON_WORDS = {"mark", "ale", "sala", "mora", "habo", "bjuv", "boden", "berg", "gnosjö", "ljusdal", "torsby",
                 "vara", "hylte", "moss", "malung", "salem", "lysekil", "orust", "tanum", "säter", "älvdalen",
                 "storuman", "sorsele", "tierp", "heby", "flen", "kil", "ånge", "nora", "laxå", "ydre", "berga"}


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[re.Pattern, tuple[str, ...], str]]:
    municipalities = json.loads(MUNICIPALITIES_PATH.read_text(encoding="utf-8"))
    kommun_names: dict[str, str] = {}
    localities: dict[str, set[str]] = {}
    for kommun in municipalities:
        short = kommun["short_name"]
        for name in {short, kommun["name"], short + "s", f"{short} kommun", f"{short} municipality"}:
            kommun_names[name] = kommun["code"]
        for locality in kommun["localities"]:
            if len(locality) >= 4 and "," not in locality and " och " not in locality:
                localities.setdefault(locality, set()).add(kommun["code"])

    # Kommun names win over homonymous localities; a locality found in a few kommuner
    # ("Lindholmen") maps to all of them
    names: dict[str, tuple[str, ...]] = {name: (code,) for name, code in kommun_names.items()}
    for name, codes in localities.items():
        if name not in names and len(codes) <= 3:
            names[name] = tuple(sorted(codes))

    patterns = []
    for name, codes in names.items():
        flags = 0 if (name.lower() in _COMMON_WORDS or len(name) < 6) else re.I
        patterns.append((re.compile(rf"(?<![\wåäö]){re.escape(name)}(?![\wåäö])", flags), codes, name))
    # Longest names first so "Upplands Väsby" wins over "Väsby"
    patterns.sort(key=lambda item: -len(item[2]))
    return patterns


class CorpusPlaces:
    """Fallback for places missing from Wikidata ("Veda"): a query word that the corpus
    mentions almost only in one kommun's documents points to that kommun."""

    def __init__(self, chunks: list[dict], min_mentions: int = 3, share: float = 0.8):
        self.min_mentions = min_mentions
        self.share = share
        self.counts: dict[str, Counter] = defaultdict(Counter)
        for chunk in chunks:
            if chunk["kind"] != "law" and chunk.get("kommun_code"):
                # Place names are capitalised: counting only those keeps the table small
                for word in {w.lower() for w in _PROPER_NOUN.findall(chunk["text"])}:
                    self.counts[word][chunk["kommun_code"]] += 1

    def detect(self, *texts: str) -> list[str]:
        found = []
        for word in _WORD.findall(" ".join(t for t in texts if t).lower()):
            counts = self.counts.get(word)
            if not counts or word in SWEDISH_STOPWORDS:
                continue
            code, top = counts.most_common(1)[0]
            total = sum(counts.values())
            # Concentrated in one kommun, and not a common word there either
            if top >= self.min_mentions and top / total >= self.share and len(counts) <= 3 and code not in found:
                found.append(code)
        return found


_WORD = re.compile(r"[a-zåäöé]{4,}")
_PROPER_NOUN = re.compile(r"(?<![\w])[A-ZÅÄÖ][a-zåäöé]{3,}")


def detect_kommuner(*texts: str) -> list[str]:
    """Kommun codes mentioned in the texts, in order of appearance, most specific names first."""
    found: dict[str, int] = {}
    text = " \n ".join(t for t in texts if t)
    taken: list[tuple[int, int]] = []
    for pattern, codes, _ in _patterns():
        for match in pattern.finditer(text):
            span = match.span()
            if any(start < span[1] and span[0] < end for start, end in taken):
                continue
            taken.append(span)
            for code in codes:
                found.setdefault(code, span[0])
    return sorted(found, key=found.get)


@lru_cache(maxsize=1)
def _names_by_code() -> dict[str, str]:
    return {m["code"]: m["short_name"] for m in json.loads(MUNICIPALITIES_PATH.read_text(encoding="utf-8"))}


def kommun_label(code: str) -> str:
    """'0115' -> 'Vallentuna (0115)' for display."""
    name = _names_by_code().get(code)
    return f"{name} ({code})" if name else code
