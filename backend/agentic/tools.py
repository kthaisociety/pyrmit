"""
Tools over the structured local corpus (laws -> chapters -> §; kommun -> documents -> chunks/pages).

Every tool returns compact text for the model plus the chunk ids it exposed, so the benchmark can
measure which evidence the agent actually looked at.
"""

import base64
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field

from corpus.common import MUNICIPALITIES_PATH, WEB_DIR
from corpus.plans import PLANS_PATH
from localrag.gazetteer import detect_kommuner, kommun_label
from localrag.index import chunk_text

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
}


@dataclass
class ToolResult:
    text: str
    chunk_ids: list[str] = field(default_factory=list)
    image_png: bytes | None = None


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

    def ids_with_prefix(self, prefix: str, limit: int = 2) -> list[str]:
        return [chunk_id for chunk_id in self.chunks if chunk_id.startswith(prefix)][:limit]

    def doc_chunk_ids(self, doc_id: str) -> list[str]:
        return self.doc_ids.get(doc_id, [])

    def documents(self, codes: set[str], doc_type: str | None, title_contains: str | None) -> list[dict]:
        return [dict(d, chunks=len(self.doc_ids[d["doc_id"]])) for d in self.docs.values()
                if d["kommun_code"] in codes and (not doc_type or d["doc_type"] == doc_type)
                and (not title_contains or title_contains.lower() in d["title"].lower())]

    def doc_type_counts(self, code: str) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for doc in self.docs.values():
            if doc["kommun_code"] == code:
                counts[doc["doc_type"]] += 1
        return dict(counts)

    def grep(self, regex: re.Pattern, scope: str, codes: set[str], limit: int) -> tuple[int, list[tuple[dict, re.Match]]]:
        total, hits = 0, []
        for chunk in self.chunks.values():
            is_law = chunk["kind"] == "law"
            if (scope == "law" and not is_law) or (scope == "kommun" and is_law):
                continue
            if codes and not is_law and chunk.get("kommun_code") not in codes:
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

    def doc_chunk_ids(self, doc_id: str) -> list[str]:
        return [r[0] for r in self.store.query(
            "SELECT chunk_id FROM chunks WHERE doc_id = ? ORDER BY CAST(chunk_index AS INTEGER)", (doc_id,))]

    def documents(self, codes: set[str], doc_type: str | None, title_contains: str | None) -> list[dict]:
        sql = (f"SELECT doc_id, title, kind, doc_type, kommun, kommun_code, url, COUNT(*) AS chunks FROM chunks "
               f"WHERE kind != 'law' AND kommun_code IN ({','.join('?' * len(codes))})")
        params: list = list(codes)
        if doc_type:
            sql += " AND doc_type = ?"
            params.append(doc_type)
        if title_contains:
            sql += " AND title LIKE ?"
            params.append(f"%{title_contains}%")
        return [dict(r) for r in self.store.query(sql + " GROUP BY doc_id ORDER BY title", tuple(params))]

    def doc_type_counts(self, code: str) -> dict[str, int]:
        return {r[0]: r[1] for r in self.store.query(
            "SELECT doc_type, COUNT(DISTINCT doc_id) FROM chunks WHERE kommun_code = ? GROUP BY doc_type", (code,))}

    def grep(self, regex: re.Pattern, scope: str, codes: set[str], limit: int) -> tuple[int, list[tuple[dict, re.Match]]]:
        where, params = [], []
        if scope == "law":
            where.append("kind = 'law'")
        elif scope == "kommun":
            where.append("kind != 'law'")
        if codes:
            where.append(f"(kind = 'law' OR kommun_code IN ({','.join('?' * len(codes))}))")
            params.extend(codes)
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
            return ToolResult(f"No kommun found for '{place}'. Try the kommun name or a nearby town.")
        lines = []
        for code in codes:
            kommun = next((m for m in self.municipalities if m["code"] == code), None)
            by_type = self.corpus.doc_type_counts(code)
            lines.append(f"{kommun_label(code)} – {kommun['county'] if kommun else ''}, website "
                         f"{kommun['website'] if kommun else '?'}; {sum(by_type.values())} documents in the corpus: {by_type}")
        return ToolResult("\n".join(lines))

    def search(self, query: str, scope: str = "all", kommun: str | None = None, k: int = 8) -> ToolResult:
        """Semantic search (Swedish query works best). scope: law | kommun | all."""
        k = max(1, min(int(k or 8), 15))
        codes = self._kommun_codes(kommun)
        # Hybrid when a BM25 index is available: exact Swedish wording ("20 meter", plan names) that the
        # embedding model ranks low still comes up
        hybrid = "stem" in self.retriever.bm25
        result = self.retriever.search(query, query_sv=query, k=k, mode="hybrid" if hybrid else "dense",
                                       dense_lang="sv", bm25_mode="stem" if hybrid else None,
                                       kommuner=codes if codes is not None else "auto")
        lines, ids = [], []
        pools = {"law": ["law"], "kommun": ["local"], "all": ["law", "local"]}.get(scope, ["law", "local"])
        for pool in pools:
            for hit in result[pool]:
                lines.append(self._line(hit.chunk))
                ids.append(hit.chunk["chunk_id"])
        header = f"kommun filter: {', '.join(kommun_label(c) for c in result['kommuner']) or 'none'}"
        return ToolResult(header + "\n" + ("\n".join(lines) or "No results."), ids)

    def grep(self, pattern: str, kommun: str | None = None, scope: str = "all", max_results: int = 15) -> ToolResult:
        """Case-insensitive regex over chunk texts: exact terms, plan numbers, property designations."""
        try:
            regex = re.compile(pattern, re.I)
        except re.error as exc:
            return ToolResult(f"Invalid regex: {exc}")
        codes = set(self._kommun_codes(kommun) or [])
        total, hits = self.corpus.grep(regex, scope, codes, max_results)
        lines, ids = [], []
        for chunk, match in hits:
            text = " ".join(chunk_text(chunk).split())
            start = max(0, match.start() - 150)
            lines.append(self._line(chunk, "…" + text[start:start + SNIPPET] + "…"))
            ids.append(chunk["chunk_id"])
        return ToolResult(f"{total} matching chunks (showing {len(lines)}):\n" + ("\n".join(lines) or "No match."), ids)

    def list_documents(self, kommun: str, doc_type: str | None = None, title_contains: str | None = None,
                       limit: int = 40) -> ToolResult:
        codes = set(self._kommun_codes(kommun) or [])
        if not codes:
            return ToolResult(f"Unknown kommun '{kommun}'.")
        docs = self.corpus.documents(codes, doc_type, title_contains)
        lines = [f"{d['doc_id']} | {d['doc_type']} | {d['kind']} | {d['title'][:110]} ({d['chunks']} chunks)"
                 for d in docs[:limit]]
        return ToolResult(f"{len(docs)} documents (showing {len(lines)}). doc_type values: detaljplan, oversiktsplan, "
                          f"bygglov, avlopp, taxa, strandskydd, other\n" + "\n".join(lines))

    def read(self, chunk_id: str | None = None, doc_id: str | None = None, start: int = 0, count: int = 4) -> ToolResult:
        """Read a chunk with its neighbours, or a document from chunk position `start`."""
        if chunk_id:
            chunk = self.corpus.chunk(chunk_id)
            if chunk is None:
                return ToolResult(f"Unknown chunk_id {chunk_id}.")
            doc_id = chunk["doc_id"]
            ids = self.corpus.doc_chunk_ids(doc_id)
            start = max(0, ids.index(chunk_id) - 1)
            count = max(int(count or 3), 3)
        doc = self.corpus.doc(doc_id) if doc_id else None
        if doc is None:
            return ToolResult(f"Unknown doc_id {doc_id}.")
        ids = self.corpus.doc_chunk_ids(doc_id)
        start = max(0, int(start or 0))
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
        wanted = LAW_ALIASES.get(law.strip().lower(), law.strip().lower())
        normalized = re.sub(r"\s+", " ", section.replace("§§", "§")).strip()
        if "§" not in normalized:
            normalized += " §"
        hits = self.corpus.law_hits(wanted, normalized)
        if not hits:
            return ToolResult(f"No section '{normalized}' in '{law}'. Available laws: {self.corpus.law_titles()}. "
                              "Sections look like '9 kap. 4 §' or '13 §' (laws without chapters).")
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
            return ToolResult(f"Unknown kommun '{kommun}'.")
        found = [plan for code in codes for plan in self._plans().get(code, [])]
        if not found:
            return ToolResult("No plan registry for this kommun; use list_documents(doc_type='detaljplan').")
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
            return ToolResult(f"Unknown plan_id {plan_id}; get ids from the plans tool.")
        rules = [r for r in plan["provisions"] if not topic or topic in r["topics"]]
        docs = "\n".join(f"  {d['role']}: {d['doc_id']} {d.get('title') or ''}{' (scanned, see view_pdf_page)' if d['scanned'] else ''}"
                         for d in plan["documents"])
        header = (f"{plan['name']} ({plan['kommun']}), status {plan['status']}"
                  f"{', laga kraft ' + plan['laga_kraft'] if plan.get('laga_kraft') else ''}\nDocuments:\n{docs}\n")
        if not rules:
            return ToolResult(header + "No provisions extracted (scanned map or none in the text): read the plankarta "
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

    def view_map_area(self, doc_id: str, around: str, page: int = 1, size: str = "medium") -> ToolResult:
        """Zoom on a plankarta around a label (property designation such as '5:125', a street, a code), and list
        the codes printed in that area with their meaning: which zone rules apply to a given property."""
        match = re.fullmatch(r"pdf:(\d{4}):(\w+)", doc_id or "")
        if not match:
            return ToolResult("Only crawled PDFs (doc_id 'pdf:<code>:<id>') can be viewed.")
        path = WEB_DIR / match.group(1) / "pdf" / f"{match.group(2)}.pdf"
        if not path.exists():
            return ToolResult(f"PDF file missing for {doc_id}.")
        import pymupdf

        pdf = pymupdf.open(path)
        page_index = max(1, int(page or 1)) - 1
        if page_index >= len(pdf):
            return ToolResult(f"{doc_id} has {len(pdf)} pages.")
        target = pdf[page_index]
        hits = target.search_for(str(around).strip())
        if not hits:
            return ToolResult(f"'{around}' is not printed as text on page {page_index + 1} of {doc_id} (scanned map, or "
                              "another spelling: try the bare number like '5:125', or view_pdf_page).")
        margin = {"near": 150, "medium": 250, "wide": 450}.get(size, 250)

        def area(hit):  # search and word coordinates are unrotated; rendering uses the rotated page
            return pymupdf.Rect(hit.x0 - margin, hit.y0 - margin, hit.x1 + margin, hit.y1 + margin) & target.mediabox

        def codes_in(clip) -> list[str]:
            codes = []
            for word in (w[4] for w in target.get_text("words", clip=clip)):
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
        text = (f"{cite}Area of page {page_index + 1} of {doc_id} around '{around}' ({len(hits)} occurrence(s) on the "
                f"page) attached as an image. Codes printed in this area:\n" + ("\n".join(lines) or "none") +
                "\nA code applies to the zone (outlined area) it is printed in: check on the image which zone the "
                "property is in before applying a rule.")
        return ToolResult(text, chunk_ids, image_png=png)

    def view_pdf_page(self, doc_id: str, page: int = 1) -> ToolResult:
        """Render a PDF page as an image (plankarta maps, tables, scanned pages)."""
        match = re.fullmatch(r"pdf:(\d{4}):(\w+)", doc_id or "")
        if not match:
            return ToolResult("Only crawled PDFs (doc_id 'pdf:<code>:<id>') can be viewed.")
        path = WEB_DIR / match.group(1) / "pdf" / f"{match.group(2)}.pdf"
        if not path.exists():
            return ToolResult(f"PDF file missing for {doc_id}.")
        import pymupdf

        pdf = pymupdf.open(path)
        page_index = max(1, int(page or 1)) - 1
        if page_index >= len(pdf):
            return ToolResult(f"{doc_id} has {len(pdf)} pages.")
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
     "description": "Semantic search over Swedish laws and municipal documents. Write the query in Swedish with the legal/planning terms (bygglov, detaljplan, strandskydd, enskilt avlopp...). scope: 'law', 'kommun' or 'all'. Give the kommun to restrict municipal results.",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string"}, "scope": {"type": "string", "enum": ["law", "kommun", "all"]},
         "kommun": {"type": "string", "description": "kommun name or 4-digit code"},
         "k": {"type": "integer", "description": "results per pool, max 15"}}, "required": ["query"]}},
    {"type": "function", "name": "grep",
     "description": "Exact / regex search (case-insensitive) in chunk texts. Best for precise terms: plan numbers (B670323), property designations (Vallentuna-Mörby 1:357), place names, 'nockhöjd', 'byggnadsarea', amounts in kronor.",
     "parameters": {"type": "object", "properties": {
         "pattern": {"type": "string"}, "kommun": {"type": "string"},
         "scope": {"type": "string", "enum": ["law", "kommun", "all"]}}, "required": ["pattern"]}},
    {"type": "function", "name": "list_documents",
     "description": "List the documents of a kommun (web pages and PDFs), optionally by doc_type (detaljplan, oversiktsplan, bygglov, avlopp, taxa, strandskydd, other) or title substring.",
     "parameters": {"type": "object", "properties": {
         "kommun": {"type": "string"}, "doc_type": {"type": "string"}, "title_contains": {"type": "string"}},
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
     "description": "Zoom on a plankarta around a label printed on the map (property designation such as '5:125', a street or block name) and get the codes printed there with their meaning. Use it whenever the question is about a specific property or place inside a detaljplan: the plan's rules differ by zone and only the map tells which zone the property is in. size: near | medium | wide.",
     "parameters": {"type": "object", "properties": {
         "doc_id": {"type": "string", "description": "the plankarta doc_id (from plans / plan_rules)"},
         "around": {"type": "string", "description": "text printed on the map, e.g. '5:125'"},
         "page": {"type": "integer"}, "size": {"type": "string", "enum": ["near", "medium", "wide"]}},
         "required": ["doc_id", "around"]}},
    {"type": "function", "name": "view_pdf_page",
     "description": "Look at a page of a crawled PDF as an image: plankarta maps (zones, heights, legend), tables, scanned documents. Expensive: use only when the text is missing or spatial.",
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
        return ToolResult(f"Unknown tool {name}.")
    try:
        return handlers[name](**arguments)
    except TypeError as exc:
        return ToolResult(f"Bad arguments for {name}: {exc}")


def image_message(result: ToolResult) -> dict:
    data = base64.b64encode(result.image_png).decode()
    return {"role": "user", "content": [
        {"type": "input_text", "text": result.text},
        {"type": "input_image", "image_url": f"data:image/png;base64,{data}"},
    ]}
