"""
Tools over the structured local corpus (laws -> chapters -> §; kommun -> documents -> chunks/pages).

Every tool returns compact text for the model plus the chunk ids it exposed, so the benchmark can
measure which evidence the agent actually looked at.
"""

import base64
import json
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field

from corpus.common import MUNICIPALITIES_PATH, WEB_DIR
from corpus.plans import PLANS_PATH
from localrag.gazetteer import detect_kommuner, kommun_label
from localrag.index import chunk_text

logger = logging.getLogger(__name__)
SNIPPET = 350
READ_LIMIT = 9000

# Short names the model is likely to use -> words of the statute title
LAW_ALIASES = {
    "pbl": "plan- och bygglag", "plan- och bygglagen": "plan- och bygglag",
    "pbf": "plan- och byggförordning", "mb": "miljöbalk", "miljöbalken": "miljöbalk",
    "jb": "jordabalk", "jordabalken": "jordabalk", "fbl": "fastighetsbildningslag",
    "fastighetsbildningslagen": "fastighetsbildningslag", "brl": "bostadsrättslag",
    "al": "anläggningslag", "anläggningslagen": "anläggningslag", "fmh": "miljöfarlig verksamhet och hälsoskydd",
    "lav": "allmänna vattentjänster", "expropriationslagen": "expropriationslag",
    "kml": "kulturmiljölag", "kulturmiljölagen": "kulturmiljölag",
    "mpf": "miljöprövningsförordning", "mbf": "miljöbedömningsförordning", "lrl": "ledningsrättslag",
    "ledningsrättslagen": "ledningsrättslag", "bostadsrättslagen": "bostadsrättslag",
}


def resolve_cited(get_chunk, chunk_id: str, seen) -> dict | None:
    """A chunk an answer cites. The model sometimes miscopies an id after its first characters ('4463112e2b2b1435'
    for '4463112e3a73206d', ~1 % of citations): it then resolves to the one chunk it was shown (`seen`) that
    shares the longest prefix, of at least 8 characters."""
    chunk = get_chunk(chunk_id)
    if chunk is not None or not seen:
        return chunk
    scored = sorted(((len(os.path.commonprefix([chunk_id, shown])), shown) for shown in set(seen)), reverse=True)
    if scored[0][0] >= 8 and (len(scored) == 1 or scored[1][0] < scored[0][0]):
        return get_chunk(scored[0][1])
    return None


def _fold(text: str) -> str:
    """Lower case without Swedish diacritics: the model writes 'miljoprovningsforordning'."""
    return text.lower().translate(str.maketrans("åäöé", "aaoe"))


def normalize_section(section: str) -> str:
    """'9 kap. 4 §' from '9 kap 4§', '9:4', '4a §', '7 kap. 18 c § punkt 1'."""
    text = re.sub(r"\s+", " ", section.replace("§§", "§")).strip()
    if match := re.fullmatch(r"(\d+ ?[a-z]?):(\d+ ?[a-z]?)", text):
        text = f"{match.group(1)} kap. {match.group(2)} §"
    text = re.sub(r"\bkap\b\.?", "kap.", text)
    text = re.sub(r"(\d)\s*([a-z])\s*(?=§|kap\.)", r"\1 \2 ", text)  # "4a §" -> "4 a §"
    text = re.sub(r"(\d)\s*§", r"\1 §", text)
    return text.split("§")[0].strip() + " §"  # drop "punkt 1", "första stycket"


@dataclass
class ToolResult:
    text: str
    chunk_ids: list[str] = field(default_factory=list)
    image_png: bytes | None = None
    # Why the call returned nothing usable: unknown_id (an id the corpus does not have), bad_args, not_found (no such
    # kommun / section / label), no_data (nothing to show). Recorded in the steps: the benchmark counts them per tool
    error: str = ""


def _failed(kind: str, text: str) -> ToolResult:
    return ToolResult(text, error=kind)


# corpus/extract.py document types: the filter of search, grep and list_documents
DOC_TYPES = ("detaljplan", "oversiktsplan", "bygglov", "strandskydd", "avlopp", "taxa", "other")


def parse_doc_types(value) -> list[str] | None:
    """doc_types as the model writes them: a list, one string, "detaljplan, oversiktsplan", "översiktsplan".
    ValueError on an unknown type."""
    if not value:
        return None
    values = [value] if isinstance(value, str) else list(value)
    types = [_fold(v).strip() for item in values for v in str(item).split(",") if v.strip()]
    unknown = [t for t in types if t not in DOC_TYPES]
    if unknown:
        raise ValueError(f"Unknown doc_types {unknown}: use {', '.join(DOC_TYPES)}.")
    return list(dict.fromkeys(types)) or None


def _label_key(text: str) -> str:
    """A printed label as OCR may read it: '5.125' / '5,125' / '5;125' for the property number '5:125'."""
    text = text.strip(" .,;()[]").lower()
    return re.sub(r"^(\d+)[.,;:](\d+)$", r"\1:\2", text)


class _MemoryCorpus:
    """Chunks held in RAM (LocalRetriever, used by the benchmarks on a corpus subset)."""

    def __init__(self, chunks: list[dict]):
        self.chunks = {c["chunk_id"]: c for c in chunks}
        self.docs: dict[str, dict] = {}
        self.doc_ids: dict[str, list[str]] = defaultdict(list)
        for chunk in chunks:
            self.docs.setdefault(chunk["doc_id"], {key: chunk.get(key) for key in
                                                   ("doc_id", "title", "kind", "doc_type", "kommun", "kommun_code", "url")})
            self.doc_ids[chunk["doc_id"]].append(chunk["chunk_id"])
        for ids in self.doc_ids.values():
            ids.sort(key=lambda chunk_id: self.chunks[chunk_id].get("chunk_index") or 0)

    def chunk(self, chunk_id: str) -> dict | None:
        return self.chunks.get(chunk_id)

    def doc(self, doc_id: str) -> dict | None:
        return self.docs.get(doc_id)

    def doc_ids_ending(self, suffix: str, limit: int = 2) -> list[str]:
        return [doc_id for doc_id in self.docs if doc_id.endswith(":" + suffix)][:limit]

    def ids_with_prefix(self, prefix: str, limit: int = 2) -> list[str]:
        return [chunk_id for chunk_id in self.chunks if chunk_id.startswith(prefix)][:limit]

    def doc_chunk_ids(self, doc_id: str) -> list[str]:
        return self.doc_ids.get(doc_id, [])

    def documents(self, codes: set[str], doc_types: list[str] | None, title_contains: str | None) -> list[dict]:
        docs = [dict(d, chunks=len(self.doc_ids[d["doc_id"]])) for d in self.docs.values()
                if d["kommun_code"] in codes and (not doc_types or d["doc_type"] in doc_types)
                and (not title_contains or title_contains.lower() in d["title"].lower())]
        return sorted(docs, key=lambda d: d["title"])

    def doc_type_counts(self, code: str) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for doc in self.docs.values():
            if doc["kommun_code"] == code:
                counts[doc["doc_type"]] += 1
        return dict(counts)

    def grep(self, regex: re.Pattern, scope: str, codes: set[str], limit: int, doc_types: list[str] | None = None,
             title_contains: str | None = None) -> tuple[int, list[tuple[dict, re.Match]]]:
        total, hits = 0, []
        for chunk in self.chunks.values():
            is_law = chunk["kind"] == "law"
            if (scope == "law" and not is_law) or (scope == "kommun" and is_law):
                continue
            if codes and not is_law and chunk.get("kommun_code") not in codes:
                continue
            if (doc_types or title_contains) and (  # a document filter leaves the statutes out
                    is_law or (doc_types and chunk.get("doc_type") not in doc_types)
                    or (title_contains and title_contains.lower() not in (chunk.get("title") or "").lower())):
                continue
            match = regex.search(" ".join(chunk_text(chunk).split()))
            if match:
                total += 1
                if len(hits) < limit:
                    hits.append((chunk, match))
        return total, hits

    def law_hits(self, wanted: str, section: str) -> list[dict]:
        return [c for c in self.chunks.values() if c["kind"] == "law" and wanted in c["title"].lower()
                and c.get("section") == section]

    def law_titles(self) -> list[str]:
        return sorted({c["title"] for c in self.chunks.values() if c["kind"] == "law"})


# Kinds of kommun chunks, spelled out so SQLite uses the (kind, kommun_code) index: `kind != 'law'` or no
# kind filter scans the whole chunks table (~0.7 s per query, find_kommun and list_documents took seconds)
LOCAL_KINDS = "('page', 'pdf')"  # corpus/extract.py: web pages and PDFs


class _DiskCorpus:
    """Chunks in SQLite (DiskStore): nothing is loaded up front."""

    GREP_SCAN_LIMIT = 2000

    def __init__(self, store):
        self.store = store

    def chunk(self, chunk_id: str) -> dict | None:
        return self.store.chunk(chunk_id)

    def ids_with_prefix(self, prefix: str, limit: int = 2) -> list[str]:
        # Range on the chunk_id index: hex ids sort below the next character after "f"
        return [r[0] for r in self.store.query("SELECT chunk_id FROM chunks WHERE chunk_id >= ? AND chunk_id < ? "
                                               "LIMIT ?", (prefix, prefix + "g", limit))]

    def doc(self, doc_id: str) -> dict | None:
        rows = self.store.query("SELECT doc_id, title, kind, doc_type, kommun, kommun_code, url FROM chunks "
                                "WHERE doc_id = ? LIMIT 1", (doc_id,))
        return dict(rows[0]) if rows else None

    def doc_ids_ending(self, suffix: str, limit: int = 2) -> list[str]:
        # No index on the suffix (~0.3 s): only a fallback for an id read() could not resolve
        return [r[0] for r in self.store.query("SELECT DISTINCT doc_id FROM chunks WHERE doc_id GLOB ? LIMIT ?",
                                               (f"*:{suffix}", limit))]

    def doc_chunk_ids(self, doc_id: str) -> list[str]:
        return [r[0] for r in self.store.query(
            "SELECT chunk_id FROM chunks WHERE doc_id = ? ORDER BY CAST(chunk_index AS INTEGER)", (doc_id,))]

    @staticmethod
    def _filters(doc_types: list[str] | None, title_contains: str | None) -> tuple[str, list]:
        sql, params = "", []
        if doc_types:
            sql += f" AND doc_type IN ({','.join('?' * len(doc_types))})"
            params += doc_types
        if title_contains:
            sql += " AND title LIKE ?"
            params.append(f"%{title_contains}%")
        return sql, params

    def documents(self, codes: set[str], doc_types: list[str] | None, title_contains: str | None) -> list[dict]:
        filters, params = self._filters(doc_types, title_contains)
        sql = (f"SELECT doc_id, title, kind, doc_type, kommun, kommun_code, url, COUNT(*) AS chunks FROM chunks "
               f"WHERE kind IN {LOCAL_KINDS} AND kommun_code IN ({','.join('?' * len(codes))}){filters}")
        return [dict(r) for r in self.store.query(sql + " GROUP BY doc_id ORDER BY title", (*codes, *params))]

    def doc_type_counts(self, code: str) -> dict[str, int]:
        return {r[0]: r[1] for r in self.store.query(
            f"SELECT doc_type, COUNT(DISTINCT doc_id) FROM chunks WHERE kind IN {LOCAL_KINDS} AND kommun_code = ? "
            "GROUP BY doc_type", (code,))}

    def grep(self, regex: re.Pattern, scope: str, codes: set[str], limit: int, doc_types: list[str] | None = None,
             title_contains: str | None = None) -> tuple[int, list[tuple[dict, re.Match]]]:
        # Each branch on the (kind, kommun_code) index: "kind != 'law'" or "kind = 'law' OR kommun_code IN" scanned
        # the whole table with the regex (~5 s for a kommun-filtered grep instead of 0.25 s)
        local = f"kind IN {LOCAL_KINDS}"
        if codes:
            local += f" AND kommun_code IN ({','.join('?' * len(codes))})"
        filters, filter_params = self._filters(doc_types, title_contains)
        local += filters
        if filters and scope != "law":
            scope = "kommun"  # a document filter leaves the statutes out
        where = [{"law": "kind = 'law'", "kommun": local}.get(scope, f"(kind = 'law' OR ({local}))")]
        params: list = (list(codes) + filter_params) if scope != "law" else []
        where.append("(header || ' ' || text) REGEXP ?")
        params.append(regex.pattern)
        # The count is capped: an unfiltered regex over the whole corpus scans every row once
        rows = self.store.query(f"SELECT * FROM chunks WHERE {' AND '.join(where)} LIMIT {self.GREP_SCAN_LIMIT}",
                                tuple(params))
        hits = []
        for row in rows[:limit]:
            chunk = self.store._chunk(row)
            match = regex.search(" ".join(chunk_text(chunk).split()))
            if match:
                hits.append((chunk, match))
        return len(rows), hits

    def law_hits(self, wanted: str, section: str) -> list[dict]:
        rows = self.store.query("SELECT * FROM chunks WHERE kind = 'law' AND lower(title) LIKE ? AND section = ?",
                                (f"%{wanted}%", section))
        return [self.store._chunk(r) for r in rows]

    def law_titles(self) -> list[str]:
        return [r[0] for r in self.store.query("SELECT DISTINCT title FROM chunks WHERE kind = 'law' ORDER BY title")]


class CorpusTools:
    def __init__(self, retriever):
        self.retriever = retriever
        self.corpus = _DiskCorpus(retriever.store) if hasattr(retriever, "store") else _MemoryCorpus(retriever.chunks)
        self.municipalities = json.loads(MUNICIPALITIES_PATH.read_text(encoding="utf-8"))
        self._plan_registry: dict[str, list[dict]] | None = None

    def get_chunk(self, chunk_id: str) -> dict | None:
        """A chunk by id; a truncated id (8-15 hex characters, the model sometimes drops some) is resolved
        when it is the prefix of exactly one chunk id."""
        chunk = self.corpus.chunk(chunk_id)
        if chunk is not None or not 8 <= len(chunk_id) < 16:
            return chunk
        matches = self.corpus.ids_with_prefix(chunk_id)
        return self.corpus.chunk(matches[0]) if len(matches) == 1 else None

    def warm_up(self) -> None:
        """Load the query embedding model now (lazy otherwise: ~20-30 s on the first search)."""
        embedder = getattr(self.retriever, "embedder", None)
        if embedder is not None:
            embedder.embed_query("bygglov")

    # --- helpers ------------------------------------------------------------------

    def _line(self, chunk: dict, snippet: str | None = None) -> str:
        text = snippet if snippet is not None else " ".join(chunk["text"].split())[:SNIPPET]
        where = chunk["section"] if chunk["kind"] == "law" else (chunk.get("section") or "")
        source = chunk["title"] if chunk["kind"] == "law" else f"{chunk.get('kommun')} – {chunk['title']}"
        return f"[c:{chunk['chunk_id']}] {source}{f' | {where}' if where else ''} (doc {chunk['doc_id']})\n    {text}"

    def _doc_id(self, doc_id: str | None) -> str | None:
        """The doc_id as stored: the model sometimes drops the 'pdf:' / 'page:' prefix ('0115:be42...') or copies the
        "(doc pdf:...)" of the tool output with its "doc " (14 stored reads, found by agentic.replay)."""
        doc_id = (doc_id or "").strip().strip("[]()").removeprefix("doc ").strip()
        if re.fullmatch(r"\d{4}:\w+", doc_id):
            return next((f"{kind}:{doc_id}" for kind in ("pdf", "page") if self.corpus.doc(f"{kind}:{doc_id}")), doc_id)
        # Only the hash of 'page:0115:7e86b453f43e469e', often written as a chunk id ('c:7e86b453f43e469e')
        if re.fullmatch(r"[0-9a-f]{16}", doc_id) and self.corpus.doc(doc_id) is None:
            matches = self.corpus.doc_ids_ending(doc_id)
            if len(matches) == 1:
                return matches[0]
        return doc_id or None

    def _kommun_codes(self, kommun: str | None) -> list[str] | None:
        if not kommun:
            return None
        if re.fullmatch(r"\d{4}", kommun.strip()):
            return [kommun.strip()]
        codes = detect_kommuner(kommun) or detect_kommuner(kommun.title())
        return codes or None

    # --- tools --------------------------------------------------------------------

    def find_kommun(self, place: str) -> ToolResult:
        codes = detect_kommuner(place) or detect_kommuner(place.title()) or self.retriever.places.detect(place)
        if not codes:
            return _failed("not_found", f"No kommun found for '{place}'. Try the kommun name or a nearby town.")
        # "Kårsta, Vallentuna": the kommun named outright first, not the other kommun that has a Kårsta
        names = {m["code"]: m["short_name"] for m in self.municipalities}
        named = [c for c in codes if names.get(c) and re.search(rf"\b{re.escape(names[c])}\b", place, re.I)]
        codes = named + [c for c in codes if c not in named]
        lines = []
        for code in codes:
            kommun = next((m for m in self.municipalities if m["code"] == code), None)
            by_type = self.corpus.doc_type_counts(code)
            lines.append(f"{kommun_label(code)} – {kommun['county'] if kommun else ''}, website "
                         f"{kommun['website'] if kommun else '?'}; {sum(by_type.values())} documents in the corpus: {by_type}")
        return ToolResult("\n".join(lines))

    @staticmethod
    def _filter_note(doc_types: list[str] | None, title_contains: str | None) -> str:
        parts = ([f"doc_types {', '.join(doc_types)}"] if doc_types else []) + \
                ([f"title contains '{title_contains}'"] if title_contains else [])
        return f"; documents: {'; '.join(parts)}" if parts else ""

    def search(self, query: str, scope: str = "all", kommun: str | None = None, k: int = 8, doc_types=None,
               title_contains: str | None = None) -> ToolResult:
        """Semantic search (Swedish query works best). scope: law | kommun | all. doc_types / title_contains narrow
        the kommun documents searched (not the statutes)."""
        k = max(1, min(int(k or 8), 15))
        try:
            types = parse_doc_types(doc_types)
        except ValueError as exc:
            return _failed("bad_args", str(exc))
        title_contains = (title_contains or "").strip() or None
        codes = self._kommun_codes(kommun)
        # Hybrid when a BM25 index is available: exact Swedish wording ("20 meter", plan names) that the
        # embedding model ranks low still comes up
        hybrid = "stem" in self.retriever.bm25
        filters = {"doc_types": types, "title_contains": title_contains} if types or title_contains else {}
        result = self.retriever.search(query, query_sv=query, k=k, mode="hybrid" if hybrid else "dense",
                                       dense_lang="sv", bm25_mode="stem" if hybrid else None,
                                       kommuner=codes if codes is not None else "auto", **filters)
        lines, ids = [], []
        pools = {"law": ["law"], "kommun": ["local"], "all": ["law", "local"]}.get(scope, ["law", "local"])
        for pool in pools:
            for hit in result[pool]:
                lines.append(self._line(hit.chunk))
                ids.append(hit.chunk["chunk_id"])
        header = (f"kommun filter: {', '.join(kommun_label(c) for c in result['kommuner']) or 'none'}"
                  + self._filter_note(types, title_contains))
        return ToolResult(header + "\n" + ("\n".join(lines) or "No results."), ids)

    def grep(self, pattern: str, kommun: str | None = None, scope: str = "all", max_results: int = 15,
             doc_types=None, title_contains: str | None = None, output: str = "chunks") -> ToolResult:
        """Case-insensitive regex over chunk texts: exact terms, plan numbers, property designations.
        output='documents': which documents match and how often (one line each) instead of the passages."""
        try:
            regex = re.compile(pattern, re.I)
            types = parse_doc_types(doc_types)
        except (re.error, ValueError) as exc:
            return _failed("bad_args", f"Invalid regex: {exc}" if isinstance(exc, re.error) else str(exc))
        title_contains = (title_contains or "").strip() or None
        codes = set(self._kommun_codes(kommun) or [])
        if kommun and not codes:
            return _failed("not_found", f"Unknown kommun '{kommun}': use find_kommun first.")
        # A regex over the whole corpus scans 349k chunks (12-28 s): grep needs a kommun, or the laws only
        if not codes and scope != "law":
            return _failed("bad_args", "grep needs a kommun (name or 4-digit code), or scope='law' for the statutes only. "
                              "To search every kommun, use search.")
        max_results = max(1, min(int(max_results or 15), 40))
        by_document = output == "documents"
        total, hits = self.corpus.grep(regex, scope, codes, _DiskCorpus.GREP_SCAN_LIMIT if by_document else max_results,
                                       types, title_contains)
        note = self._filter_note(types, title_contains)
        if by_document:
            documents: dict[str, list] = {}
            for chunk, match in hits:
                documents.setdefault(chunk["doc_id"], []).append((chunk, match))
            ranked = sorted(documents.values(), key=len, reverse=True)[:max_results]
            lines, ids = [], []
            for matches in ranked:
                chunk, match = matches[0]
                text = " ".join(chunk_text(chunk).split())
                start = max(0, match.start() - 60)
                source = chunk["title"] if chunk["kind"] == "law" else f"{chunk.get('kommun')} – {chunk['title']}"
                lines.append(f"{chunk['doc_id']} | {chunk.get('doc_type') or 'law'} | {source} | {len(matches)} matching "
                             f"chunk(s), first [c:{chunk['chunk_id']}] …{text[start:start + 160]}…")
                ids.append(chunk["chunk_id"])
            return ToolResult(f"{total} matching chunks in {len(documents)} documents{note} (showing {len(lines)}, most "
                              f"matches first):\n" + ("\n".join(lines) or "No match."), ids)
        lines, ids = [], []
        for chunk, match in hits:
            text = " ".join(chunk_text(chunk).split())
            start = max(0, match.start() - 150)
            lines.append(self._line(chunk, "…" + text[start:start + SNIPPET] + "…"))
            ids.append(chunk["chunk_id"])
        return ToolResult(f"{total} matching chunks{note} (showing {len(lines)}):\n" + ("\n".join(lines) or "No match."), ids)

    def list_documents(self, kommun: str, doc_type=None, title_contains: str | None = None, limit: int = 40,
                       offset: int = 0, doc_types=None) -> ToolResult:
        codes = set(self._kommun_codes(kommun) or [])
        if not codes:
            return _failed("not_found", f"Unknown kommun '{kommun}'.")
        try:
            types = parse_doc_types(doc_types or doc_type)
        except ValueError as exc:
            return _failed("bad_args", str(exc))
        docs = self.corpus.documents(codes, types, (title_contains or "").strip() or None)
        offset, limit = max(0, int(offset or 0)), max(1, min(int(limit or 40), 100))
        lines = [f"{d['doc_id']} | {d['doc_type']} | {d['kind']} | {d['title'][:110]} ({d['chunks']} chunks)"
                 for d in docs[offset:offset + limit]]
        more = f"; next page: offset={offset + limit}" if offset + limit < len(docs) else ""
        shown = f"{offset + 1}-{offset + len(lines)}" if lines else "none"
        return ToolResult(f"{len(docs)} documents (showing {shown}{more}). doc_types: {', '.join(DOC_TYPES)}\n"
                          + "\n".join(lines))

    def read(self, chunk_id: str | None = None, doc_id: str | None = None, start: int = 0, count: int = 4) -> ToolResult:
        """Read a chunk with its neighbours, or a document from chunk position `start`."""
        if not chunk_id and doc_id and self.corpus.doc(self._doc_id(doc_id)) is None:
            chunk_id, doc_id = doc_id, None  # a chunk id passed as doc_id ("c:371d66b20e844cf5")
        if chunk_id:
            # The model copies ids as the tools print them ("[c:<id>]", "doc page:..."), passes a doc_id here, or
            # glues a chunk id to a doc prefix ("page:0305:<chunk id>"); agentic.replay checks these forms
            chunk_id = chunk_id.strip().strip("[]").removeprefix("doc ").removeprefix("c:").strip()
            chunk = self.get_chunk(chunk_id)
            if chunk is None:
                chunk = next((c for c in map(self.corpus.chunk, re.findall(r"(?<![0-9a-f])[0-9a-f]{16}(?![0-9a-f])",
                                                                           chunk_id)) if c), None)
            if chunk is None and self.corpus.doc(self._doc_id(chunk_id)) is not None:
                doc_id = chunk_id
            elif chunk is None and doc_id:
                pass  # a stale or invented chunk id next to a valid doc_id: read the document
            elif chunk is None:
                return _failed("unknown_id", f"Unknown chunk_id {chunk_id}.")
            else:
                doc_id = chunk["doc_id"]
                ids = self.corpus.doc_chunk_ids(doc_id)
                start = max(0, ids.index(chunk["chunk_id"]) - 1)
                count = max(int(count or 3), 3)
        doc_id = self._doc_id(doc_id)
        doc = self.corpus.doc(doc_id) if doc_id else None
        if doc is None:
            return _failed("unknown_id", f"Unknown doc_id {doc_id}.")
        ids = self.corpus.doc_chunk_ids(doc_id)
        start = max(0, int(start or 0))
        if start >= len(ids):
            return _failed("bad_args", f"{doc_id} has {len(ids)} chunks (positions 0-{len(ids) - 1}); start {start} is past the end.")
        selected = ids[start:start + max(1, min(int(count or 4), 12))]
        parts, size = [], 0
        for chunk_id_ in selected:
            text = chunk_text(self.corpus.chunk(chunk_id_))
            if size + len(text) > READ_LIMIT:
                break
            parts.append(f"--- [c:{chunk_id_}] position {ids.index(chunk_id_)}/{len(ids)}\n{text}")
            size += len(text)
        header = (f"{doc['title']} ({doc.get('kommun') or 'law'}, {doc['doc_type']}, {len(ids)} chunks"
                  f"{', url ' + doc['url'] if doc.get('url') else ''})")
        return ToolResult(header + "\n" + "\n".join(parts), selected[:len(parts)])

    def law_section(self, law: str, section: str) -> ToolResult:
        """Exact statute text, e.g. law='PBL', section='9 kap. 4 §'."""
        wanted = _fold(LAW_ALIASES.get(law.strip().lower(), law.strip().lower()))
        # Match on the title without diacritics, then query by that exact title
        titles = [t for t in self.corpus.law_titles() if wanted in _fold(t)]
        normalized = normalize_section(section)
        hits = [hit for title in titles for hit in self.corpus.law_hits(title.lower(), normalized)]
        if not hits:
            hint = ""
            if titles and titles[0].startswith("Plan- och bygglag") and normalized.startswith("9 kap."):
                hint = (" PBL 9 kap. was renumbered by SFS 2025:974 (bygglov 9 kap. 56-57 §, liten avvikelse 60-61 §, "
                        "förhandsbesked 74 §): find the provision by its wording with search or grep.")
            known = f"Laws: {self.corpus.law_titles()}." if not titles else f"'{law}' = {', '.join(titles)}."
            return _failed("not_found", f"No section '{normalized}' in '{law}'. {known} Sections look like '9 kap. 4 §' or "
                              f"'13 §' (laws without chapters).{hint}")
        return ToolResult("\n\n".join(f"[c:{c['chunk_id']}] {chunk_text(c)}" for c in hits), [c["chunk_id"] for c in hits])

    def _plans(self) -> dict[str, list[dict]]:
        """The plan registry (corpus.plans), by kommun code; loaded on first use."""
        if self._plan_registry is None:
            registry: dict[str, list[dict]] = defaultdict(list)
            if PLANS_PATH.exists():
                for line in PLANS_PATH.open(encoding="utf-8"):
                    plan = json.loads(line)
                    registry[plan["kommun_code"]].append(plan)
            self._plan_registry = registry
        return self._plan_registry

    def plans(self, kommun: str, query: str | None = None, status: str | None = None, limit: int = 25) -> ToolResult:
        """The kommun's detaljplaner from the registry, filtered by words of the name / document titles."""
        codes = self._kommun_codes(kommun)
        if not codes:
            return _failed("not_found", f"Unknown kommun '{kommun}'.")
        found = [plan for code in codes for plan in self._plans().get(code, [])]
        if not found:
            return _failed("no_data", "No plan registry for this kommun; use list_documents(doc_types=['detaljplan']).")
        words = [w for w in (query or "").lower().split() if len(w) > 1]
        def haystack(plan: dict) -> str:
            return " ".join([plan["name"], plan.get("plan_number") or ""] + [d.get("title") or "" for d in plan["documents"]]).lower()
        matching = [p for p in found if all(w in haystack(p) for w in words) and (not status or p["status"] == status)]
        lines = []
        for plan in sorted(matching, key=lambda p: (not p["provisions"], p["status"] != "in_force", p["name"]))[:limit]:
            topics = sorted({t for rule in plan["provisions"] for t in rule["topics"]})
            roles = ", ".join(f"{d['role']}{' (scanned)' if d['scanned'] else ''} {d['doc_id']}" for d in plan["documents"][:4])
            date = f" laga kraft {plan['laga_kraft']}" if plan.get("laga_kraft") else ""
            lines.append(f"{plan['plan_id']} | {plan['name'][:90]} | {plan['status']}{date}"
                         f"{' | nr ' + plan['plan_number'] if plan.get('plan_number') else ''} | "
                         f"{len(plan['provisions'])} rules {topics if topics else ''} | {roles or 'web page only'}")
        return ToolResult(f"{len(matching)} of {len(found)} plans (showing {len(lines)}; status: in_force, adopted, "
                          f"review, consultation, in_progress, unknown):\n" + ("\n".join(lines) or "No match."))

    def plan_rules(self, plan_id: str, topic: str | None = None) -> ToolResult:
        """A plan's planbestämmelser as extracted from its plankarta (or planbeskrivning), citeable."""
        plan = next((p for plans in self._plans().values() for p in plans if p["plan_id"] == plan_id), None)
        if plan is None:
            return _failed("unknown_id", f"Unknown plan_id {plan_id}; get ids from the plans tool.")
        rules = [r for r in plan["provisions"] if not topic or topic in r["topics"]]
        docs = "\n".join(f"  {d['role']}: {d['doc_id']} {d.get('title') or ''}{' (scanned, see view_pdf_page)' if d['scanned'] else ''}"
                         for d in plan["documents"])
        header = (f"{plan['name']} ({plan['kommun']}), status {plan['status']}"
                  f"{', laga kraft ' + plan['laga_kraft'] if plan.get('laga_kraft') else ''}\nDocuments:\n{docs}\n")
        if not rules:
            return _failed("no_data", header + "No provisions extracted (scanned map or none in the text): read the plankarta "
                              "(read / view_pdf_page) or the planbeskrivning.")
        lines = [f"[c:{r['chunk_id']}] {r['code'] + ': ' if r['code'] else ''}{r['text']}"
                 f"{' (' + r['law_ref'] + ')' if r.get('law_ref') else ''}{'' if r.get('exact', True) else ' *'}"
                 for r in rules]
        note = ("\nCodes (e1, f2, h1, B...) apply to the map areas carrying them: which area of the map has which code "
                "is only on the plankarta (view_pdf_page). * = standard wording quoted from the plankarta, the chunk "
                "cited is the plankarta.")
        return ToolResult(header + f"{len(rules)} provisions:\n" + "\n".join(lines) + note,
                          list(dict.fromkeys(r["chunk_id"] for r in rules if r["chunk_id"])))

    def _code_definitions(self, doc_id: str) -> dict[str, tuple[str, str | None]]:
        """code -> (provision text, chunk id of the legend line), from the plan registry entry of this plankarta."""
        for plans in self._plans().values():
            for plan in plans:
                if any(d["doc_id"] == doc_id for d in plan["documents"]):
                    return {r["code"]: (r["text"], r.get("chunk_id")) for r in plan["provisions"] if r.get("code")}
        return {}

    @staticmethod
    def _ocr_words(code: str, pdf_id: str, page_index: int) -> list[tuple] | None:
        """Words corpus.ocr read on a scanned page, as (Rect, text) in unrotated PDF points like get_text("words");
        None when the PDF has no OCR output with word boxes."""
        import pymupdf

        path = WEB_DIR / code / "ocr" / f"{pdf_id}.json"
        try:
            words = json.loads(path.read_text(encoding="utf-8")).get("words")
        except (OSError, ValueError):
            return None
        if not words:
            return None
        return [(pymupdf.Rect(x0, y0, x1, y1), text) for number, x0, y0, x1, y1, text, *_ in words if number == page_index]

    @staticmethod
    def _find_in_words(words: list[tuple], around: str) -> list:
        """Rects of `around` among OCR words: one word ('5:125', also read '5.125'), or consecutive words."""
        import pymupdf

        wanted = [_label_key(t) for t in around.split()]
        hits = []
        for i in range(len(words) - len(wanted) + 1):
            window = words[i:i + len(wanted)]
            if [_label_key(text) for _, text in window] == wanted:
                rect = pymupdf.Rect(window[0][0])
                for word_rect, _ in window[1:]:
                    rect |= word_rect
                hits.append(rect)
        return hits

    def view_map_area(self, doc_id: str, around: str, page: int = 1, size: str = "medium") -> ToolResult:
        """Zoom on a plankarta around a label (property designation such as '5:125', a street, a code), and list
        the codes printed in that area with their meaning: which zone rules apply to a given property. Scanned
        plankartor: the label is looked up in the words corpus.ocr read (with their positions)."""
        match = re.fullmatch(r"pdf:(\d{4}):(\w+)", self._doc_id(doc_id) or "")
        if not match:
            return _failed("bad_args", "Only crawled PDFs (doc_id 'pdf:<code>:<id>') can be viewed.")
        path = WEB_DIR / match.group(1) / "pdf" / f"{match.group(2)}.pdf"
        if not path.exists():
            return _failed("no_data", f"PDF file missing for {doc_id}.")
        import pymupdf

        pdf = pymupdf.open(path)
        page_index = max(1, int(page or 1)) - 1
        if page_index >= len(pdf):
            return _failed("bad_args", f"{doc_id} has {len(pdf)} pages.")
        target = pdf[page_index]
        hits = target.search_for(str(around).strip())
        ocr = None
        if not hits and not target.get_text("text").strip():  # a scan: no text layer
            ocr = self._ocr_words(match.group(1), match.group(2), page_index)
            if ocr is None:
                return _failed("no_data", f"Page {page_index + 1} of {doc_id} is a scan not read by the OCR yet: look "
                                          "at it with view_pdf_page.")
            hits = self._find_in_words(ocr, str(around))
        if not hits:
            where = "read by the OCR on the scanned" if ocr is not None else "printed as text on"
            return _failed("not_found", f"'{around}' is not {where} page {page_index + 1} of {doc_id} (another spelling: "
                              "try the bare number like '5:125', or view_pdf_page).")
        margin = {"near": 150, "medium": 250, "wide": 450}.get(size, 250)

        def area(hit):  # search and word coordinates are unrotated; rendering uses the rotated page
            return pymupdf.Rect(hit.x0 - margin, hit.y0 - margin, hit.x1 + margin, hit.y1 + margin) & target.mediabox

        def words_in(clip) -> list[str]:
            if ocr is not None:
                return [text for rect, text in ocr if rect.intersects(clip)]
            return [w[4] for w in target.get_text("words", clip=clip)]

        def codes_in(clip) -> list[str]:
            codes = []
            for word in words_in(clip):
                if re.fullmatch(r"(?:[a-zåäö]\d{1,2})+", word):        # "h3e3f1f3o3": several codes printed together
                    codes += re.findall(r"[a-zåäö]\d{1,2}", word)
                elif re.fullmatch(r"[A-ZÅÄÖ]{1,4}\d?|\+\d{1,3}[.,]\d{1,2}", word):
                    codes.append(word)
            return list(dict.fromkeys(codes))

        # The label also appears in the title block or legend: keep the occurrence surrounded by map codes
        hit = max(hits, key=lambda h: len(codes_in(area(h))))
        clip = area(hit)
        shown = (clip * target.rotation_matrix) & target.rect
        zoom = 1200 / max(shown.width, shown.height)
        png = target.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=shown).tobytes("png")
        definitions = self._code_definitions(doc_id)
        codes = codes_in(clip)
        # Each code cites the legend chunk that defines it, so the answer's citations hold the rule's wording
        lines = [(f"[c:{definitions[code][1]}] " if definitions[code][1] else "") + f"{code}: {definitions[code][0]}"
                 if code in definitions else f"{code}: (meaning not in the registry: check the legend with plan_rules "
                 "/ read)" for code in codes]
        legend_ids = [definitions[code][1] for code in codes if code in definitions and definitions[code][1]]
        chunk_ids = list(dict.fromkeys(self.corpus.doc_chunk_ids(doc_id)[:1] + legend_ids))
        cite = f"[c:{chunk_ids[0]}] " if chunk_ids else ""
        scanned = (" The map is a scan: the label and codes were read by OCR, check them on the image."
                   if ocr is not None else "")
        text = (f"{cite}Area of page {page_index + 1} of {doc_id} around '{around}' ({len(hits)} occurrence(s) on the "
                f"page) attached as an image.{scanned} Codes printed in this area:\n" + ("\n".join(lines) or "none") +
                "\nA code applies to the zone (outlined area) it is printed in: check on the image which zone the "
                "property is in before applying a rule.")
        return ToolResult(text, chunk_ids, image_png=png)

    def view_pdf_page(self, doc_id: str, page: int = 1) -> ToolResult:
        """Render a PDF page as an image (plankarta maps, tables, scanned pages)."""
        match = re.fullmatch(r"pdf:(\d{4}):(\w+)", self._doc_id(doc_id) or "")
        if not match:
            return _failed("bad_args", "Only crawled PDFs (doc_id 'pdf:<code>:<id>') can be viewed.")
        path = WEB_DIR / match.group(1) / "pdf" / f"{match.group(2)}.pdf"
        if not path.exists():
            return _failed("no_data", f"PDF file missing for {doc_id}.")
        import pymupdf

        pdf = pymupdf.open(path)
        page_index = max(1, int(page or 1)) - 1
        if page_index >= len(pdf):
            return _failed("bad_args", f"{doc_id} has {len(pdf)} pages.")
        target = pdf[page_index]
        # ~1600 px on the long side: legible for legends without blowing up the context
        zoom = 1600 / max(target.rect.width, target.rect.height)
        png = target.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")
        return ToolResult(f"Page {page_index + 1}/{len(pdf)} of {doc_id} attached as an image.", image_png=png)


TOOL_SCHEMAS = [
    {"type": "function", "name": "find_kommun",
     "description": "Resolve a place name (kommun, town, village) to its kommun code and see which document types the corpus has for it.",
     "parameters": {"type": "object", "properties": {"place": {"type": "string"}}, "required": ["place"]}},
    {"type": "function", "name": "search",
     "description": "Semantic search over Swedish laws and municipal documents. Write the query in Swedish with the legal/planning terms (bygglov, detaljplan, strandskydd, enskilt avlopp...). scope: 'law', 'kommun' or 'all'. Give the kommun to restrict municipal results; doc_types / title_contains restrict them to some documents (e.g. doc_types=['oversiktsplan'] for the kommun's growth intentions).",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string"}, "scope": {"type": "string", "enum": ["law", "kommun", "all"]},
         "kommun": {"type": "string", "description": "kommun name or 4-digit code"},
         "k": {"type": "integer", "description": "results per pool, max 15"},
         "doc_types": {"type": "array", "items": {"type": "string", "enum": list(DOC_TYPES)},
                       "description": "only kommun documents of these types"},
         "title_contains": {"type": "string", "description": "only kommun documents whose title contains this"}},
         "required": ["query"]}},
    {"type": "function", "name": "grep",
     "description": "Exact / regex search (case-insensitive) in chunk texts. Best for precise terms: plan numbers (B670323), property designations (Vallentuna-Mörby 1:357), place names, 'nockhöjd', 'byggnadsarea', amounts in kronor. Needs a kommun, or scope='law' (no search over every kommun). output='documents' lists which documents match and how often instead of the passages; doc_types / title_contains restrict the kommun documents.",
     "parameters": {"type": "object", "properties": {
         "pattern": {"type": "string"}, "kommun": {"type": "string"},
         "scope": {"type": "string", "enum": ["law", "kommun", "all"]},
         "doc_types": {"type": "array", "items": {"type": "string", "enum": list(DOC_TYPES)}},
         "title_contains": {"type": "string"},
         "output": {"type": "string", "enum": ["chunks", "documents"]},
         "max_results": {"type": "integer", "description": "passages or documents shown, max 40"}},
         "required": ["pattern"]}},
    {"type": "function", "name": "list_documents",
     "description": "List the documents of a kommun (web pages and PDFs) by title, optionally of some doc_types (detaljplan, oversiktsplan, bygglov, avlopp, taxa, strandskydd, other) or with a title substring. Pages of up to 100: offset for the next page.",
     "parameters": {"type": "object", "properties": {
         "kommun": {"type": "string"},
         "doc_types": {"type": "array", "items": {"type": "string", "enum": list(DOC_TYPES)}},
         "title_contains": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}},
         "required": ["kommun"]}},
    {"type": "function", "name": "read",
     "description": "Read the full text of a chunk with its neighbours (chunk_id), or of a document starting at a chunk position (doc_id, start, count).",
     "parameters": {"type": "object", "properties": {
         "chunk_id": {"type": "string"}, "doc_id": {"type": "string"},
         "start": {"type": "integer"}, "count": {"type": "integer"}}}},
    {"type": "function", "name": "law_section",
     "description": "Exact text of a statute section, e.g. law='PBL', section='9 kap. 4 §'; law='FMH', section='13 §'. Laws: PBL, PBF, MB, JB, FBL, BRL, AL (anläggningslag), FMH (förordning om miljöfarlig verksamhet och hälsoskydd), LAV (vattentjänster), expropriationslag, ledningsrättslag, kulturmiljölag, samfälligheter, miljöbedömningsförordning, miljöprövningsförordning.",
     "parameters": {"type": "object", "properties": {"law": {"type": "string"}, "section": {"type": "string"}},
                    "required": ["law", "section"]}},
    {"type": "function", "name": "plans",
     "description": "List a kommun's detaljplaner from the plan registry: plan_id, name, status (in_force, adopted, review, consultation, in_progress), laga kraft date, documents (plankarta / planbeskrivning doc_ids) and which rule topics were extracted. Filter with words of the plan or area name (query).",
     "parameters": {"type": "object", "properties": {
         "kommun": {"type": "string"}, "query": {"type": "string", "description": "words of the plan / area name"},
         "status": {"type": "string"}}, "required": ["kommun"]}},
    {"type": "function", "name": "plan_rules",
     "description": "The planbestämmelser of a plan (from plans): building area, heights, storeys, plot size, prickmark, ancillary buildings, genomförandetid..., each citeable. topic filter: building_area, height, storeys, plot_size, no_building, ancillary, roof, implementation, use, shoreline, noise, design.",
     "parameters": {"type": "object", "properties": {"plan_id": {"type": "string"}, "topic": {"type": "string"}},
                    "required": ["plan_id"]}},
    {"type": "function", "name": "view_map_area",
     "description": "Zoom on a plankarta around a label printed on the map (property designation such as '5:125', a street or block name) and get the codes printed there with their meaning. Use it whenever the question is about a specific property or place inside a detaljplan: the plan's rules differ by zone and only the map tells which zone the property is in. Works on scanned plankartor once they are OCRed (labels read by OCR: check them on the image). size: near | medium | wide. The image is shown for one step only: note what you read on it.",
     "parameters": {"type": "object", "properties": {
         "doc_id": {"type": "string", "description": "the plankarta doc_id (from plans / plan_rules)"},
         "around": {"type": "string", "description": "text printed on the map, e.g. '5:125'"},
         "page": {"type": "integer"}, "size": {"type": "string", "enum": ["near", "medium", "wide"]}},
         "required": ["doc_id", "around"]}},
    {"type": "function", "name": "view_pdf_page",
     "description": "Look at a page of a crawled PDF as an image: plankarta maps (zones, heights, legend), tables, scanned documents. Expensive: use only when the text is missing or spatial. The image is shown for one step only: note what you read on it.",
     "parameters": {"type": "object", "properties": {"doc_id": {"type": "string"}, "page": {"type": "integer"}},
                    "required": ["doc_id"]}},
]


def run_tool(tools: CorpusTools, name: str, arguments: dict) -> ToolResult:
    handlers = {
        "find_kommun": tools.find_kommun, "search": tools.search, "grep": tools.grep,
        "list_documents": tools.list_documents, "read": tools.read, "law_section": tools.law_section,
        "view_pdf_page": tools.view_pdf_page, "plans": tools.plans, "plan_rules": tools.plan_rules,
        "view_map_area": tools.view_map_area,
    }
    if name not in handlers:
        return _failed("bad_args", f"Unknown tool {name}.")
    try:
        return handlers[name](**arguments)
    except TypeError as exc:
        return _failed("bad_args", f"Bad arguments for {name}: {exc}")
    except Exception as exc:  # a tool bug must not end the run; counted as "exception" by the benchmark and the replay
        logger.exception("tool %s failed on %s", name, arguments)
        return _failed("exception", f"{name} failed: {exc!r}")


IMAGE_ONCE = ("\nThis image is attached for your next step only, then removed: write down now, in a line or two before "
              "your next tool call, what you need from it (codes, zones, values, which zone the property is in).")


def image_message(result: ToolResult) -> dict:
    data = base64.b64encode(result.image_png).decode()
    return {"role": "user", "content": [
        {"type": "input_text", "text": result.text + IMAGE_ONCE},
        {"type": "input_image", "image_url": f"data:image/png;base64,{data}"},
    ]}
