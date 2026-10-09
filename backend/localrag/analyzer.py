"""
Swedish text analysis for BM25.

Stemming alone misses Swedish compounds: "strandskyddsdispens" never matches a query for
"dispens från strandskyddet". The "compound" analyzer therefore also indexes character
5-grams of long words, so parts of a compound can match.
"""

import re
from functools import lru_cache

import Stemmer

# Common Swedish function words (Snowball list, trimmed) plus statute boilerplate
SWEDISH_STOPWORDS = frozenset("""
och det att i en jag hon som han på den med var sig för så till är men ett om hade de av icke mig du
henne då sin nu har inte hans honom skulle hennes där min man ej vid kunde något från ut när efter upp
vi dem vara vad över än dig kan sina här ha mot alla under någon eller allt mycket sedan ju denna
själv detta åt utan varit hur ingen mitt ni bli blev oss din dessa några deras blir mina samma vilken
er sådan vår blivit dess inom mellan sådant varför varje vilka ditt vem vilket sitt sådana vart dina
vars vårt våra ert era vilkas ska skall får lag kap också samt enligt
""".split())

_TOKEN = re.compile(r"[a-zåäöéü0-9]+(?:[-:][a-zåäöéü0-9]+)*")


@lru_cache(maxsize=1)
def _stemmer():
    return Stemmer.Stemmer("swedish")


def words(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.lower()) if token not in SWEDISH_STOPWORDS and len(token) > 1]


def analyze(text: str, mode: str = "stem") -> list[str]:
    """mode: "stem" (Snowball stems) or "compound" (stems + 5-grams of words longer than 8 chars)."""
    tokens = words(text)
    stems = _stemmer().stemWords(tokens)
    if mode == "stem":
        return stems
    grams = []
    for token in tokens:
        if len(token) > 8 and token.isalpha():
            grams.extend("#" + token[i:i + 5] for i in range(len(token) - 4))
    return stems + grams
