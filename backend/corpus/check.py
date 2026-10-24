"""
Checks of the corpus after a rebuild: the bugs of October 2026 (empty municipalities, statute chapters filed under
the previous one, garbled titles, duplicate and off-topic PDFs, an index or a store behind the chunks) all looked
fine in the totals. Each check prints OK / WARN / ERROR with examples; the exit code is 1 on an error.

    cd backend && python -m corpus.check                 # everything (~1 min)
    python -m corpus.check --only crawl laws             # some sections
    python -m corpus.check --delete-orphan-pdfs          # also delete the PDFs no crawl manifest references

Results go to data/corpus/check.json; the next run compares each municipality's crawl yield with it.
"""

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

from corpus.common import (CHUNKS_PATH, DATA_DIR, DOCUMENTS_PATH, INDEX_DIR, RESULTS_ROOT, LAWS_DIR, MUNICIPALITIES_PATH, WEB_DIR, read_jsonl,
                           repair_mojibake)
from corpus.pdf_filter import DECISIONS_PATH

CHECK_PATH = DATA_DIR / "check.json"
MODEL = "st-arctic-l-v2"
YIELD_DROP = 0.5  # a municipality whose pages + PDFs fall below half of the previous check


class Report:
    def __init__(self):
        self.errors = self.warnings = 0
        self.summary: dict = {}
        self.section = ""
        self.lines: list[dict] = []  # saved in check.json for the Pipeline view

    def start(self, title: str) -> None:
        self.section = title
        print(f"\n{title}")

    def line(self, level: str, message: str, examples: list | None = None) -> None:
        if level == "ERROR":
            self.errors += 1
        elif level == "WARN":
            self.warnings += 1
        self.lines.append({"section": self.section, "level": level, "message": message,
                           "examples": [str(e) for e in (examples or [])[:20]], "count": len(examples or [])})
        print(f"  {level:<5} {message}")
        for example in (examples or [])[:6]:
            print(f"          {example}")

    def check(self, ok: bool, message: str, examples: list | None = None, level: str = "ERROR") -> None:
        self.line("OK" if ok else level, message, None if ok else examples)


def _number(value: str | None) -> tuple:
    """'4 a' -> (4, 'a'): chapter / section order."""
    match = re.match(r"(\d+)\s*([a-z]?)", value or "")
    return (int(match.group(1)), match.group(2)) if match else (0, "")


def check_crawl(report: Report, previous: dict) -> dict:
    report.start("Crawl (raw/web/*/manifest.jsonl)")
    municipalities = json.loads(MUNICIPALITIES_PATH.read_text(encoding="utf-8"))
    names = {m["code"]: m["short_name"] for m in municipalities}
    with_site = [m["code"] for m in municipalities if m.get("website")]
    crawl, unfinished, parts = {}, [], []
    for code in with_site:
        manifest = WEB_DIR / code / "manifest.jsonl"
        if (WEB_DIR / code / "manifest.jsonl.part").exists():
            parts.append(names[code])
        if not manifest.exists():
            continue
        lines = manifest.read_text(encoding="utf-8").splitlines()
        done = json.loads(lines[-1]) if lines and '"done": true' in lines[-1] else None
        if done is None:
            unfinished.append(names[code])
            continue
        crawl[code] = done
    missing = [names[c] for c in with_site if c not in crawl and names[c] not in unfinished]
    report.check(not missing, f"{len(crawl)} of {len(with_site)} municipalities with a website crawled", missing)
    report.check(not unfinished, "every manifest ends with its done line", unfinished, "WARN")
    report.check(not parts, "no crawl left half-way (manifest.jsonl.part)", parts, "WARN")
    empty = [names[c] for c, d in crawl.items() if d.get("pages", 0) + d.get("pdfs", 0) == 0]
    report.check(not empty, "no municipality without pages or PDFs", empty)
    thin = [f"{names[c]}: {d['pages']} pages, {d['pdfs']} PDFs" for c, d in crawl.items()
            if 0 < d.get("pages", 0) + d.get("pdfs", 0) < 15]
    report.check(not thin, "no municipality with fewer than 15 items", thin, "WARN")
    at_cap = [names[c] for c, d in crawl.items() if d.get("max_pdfs") and d["pdfs"] >= d["max_pdfs"]]
    at_requests = [names[c] for c, d in crawl.items() if d.get("max_requests") and d["requests"] >= d["max_requests"]]
    report.check(not at_cap, f"no municipality at the PDF cap ({len(at_cap)} are: more PDFs were left)", at_cap, "WARN")
    report.check(not at_requests, f"no municipality at the request cap ({len(at_requests)} are)", at_requests, "WARN")
    caps = Counter((d.get("max_pages"), d.get("max_pdfs"), d.get("max_pdf_mb"), d.get("max_requests")) for d in crawl.values())
    report.check(len(caps) == 1, f"one set of caps for all municipalities: {dict(caps.most_common(3))}",
                 [f"(pages, PDFs, MB, requests) {k}: {v} municipalities" for k, v in caps.most_common()], "WARN")
    before = previous.get("crawl", {})
    drops = [f"{names[c]}: {before[c]} -> {d['pages'] + d['pdfs']}" for c, d in crawl.items()
             if before.get(c) and d["pages"] + d["pdfs"] < before[c] * YIELD_DROP]
    report.check(not drops, "no municipality lost half of its items since the last check", drops, "WARN")

    referenced = {(code, json.loads(line)["id"]) for code in crawl
                  for line in (WEB_DIR / code / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
                  if '"type": "pdf"' in line}
    # PDFs of the other corpus snapshots sharing this raw/ (data/small: the 2026-10-22 corpus kept for demos)
    for documents in [RESULTS_ROOT / "corpus" / "documents.jsonl", *RESULTS_ROOT.glob("*/corpus/documents.jsonl")]:
        if documents.exists() and documents.resolve() != DOCUMENTS_PATH.resolve():
            referenced |= {tuple(d["doc_id"].split(":")[1:]) for d in read_jsonl(documents) if d["doc_id"].startswith("pdf:")}
    orphans = [p for p in WEB_DIR.glob("*/pdf/*.pdf") if (p.parent.parent.name, p.stem) not in referenced]
    size = sum(p.stat().st_size for p in orphans) / 1e9
    report.check(not orphans, f"every PDF on disk is in a manifest ({len(orphans)} are not, {size:.1f} GB)",
                 [str(p) for p in orphans], "WARN")
    report.summary["crawl"] = {"municipalities": len(crawl), "pages": sum(d["pages"] for d in crawl.values()),
                               "pdfs": sum(d["pdfs"] for d in crawl.values()), "empty": empty, "at_pdf_cap": len(at_cap),
                               "orphan_pdfs": len(orphans)}
    report.summary["orphans"] = [str(p) for p in orphans]
    return {code: d["pages"] + d["pdfs"] for code, d in crawl.items()}


def check_documents(report: Report) -> None:
    report.start("Documents (documents.jsonl)")
    garbled, replaced, undecided, empty, junk, scanned = [], [], [], [], [], Counter()
    # corpus.pdf_filter decisions (keep: None = waiting for the LLM, kept meanwhile)
    decided = {d["doc_id"] for d in read_jsonl(DECISIONS_PATH) if d.get("keep") is not None} \
        if DECISIONS_PATH.exists() else set()
    by_text: dict[tuple, list[str]] = defaultdict(list)
    # A document's kommun is the site it was crawled from; joint administrations (Askersund + Laxå + Lekeberg,
    # Avesta + Fagersta + Norberg, Falun + Borlänge...) publish the other members' plans and forms on one site
    municipalities = json.loads(MUNICIPALITIES_PATH.read_text(encoding="utf-8"))
    code_of = {m["short_name"].lower(): m["code"] for m in municipalities}
    short = {m["code"]: m["short_name"] for m in municipalities}
    kommun_named = re.compile(r"\b(" + "|".join(sorted(map(re.escape, code_of), key=len, reverse=True))
                              + r")s?\s+(?:kommun|stad)\b", re.I)
    elsewhere: Counter = Counter()
    kinds, kommuner, types, per_kommun = Counter(), set(), Counter(), Counter()
    for doc in read_jsonl(DOCUMENTS_PATH):
        kinds[doc["kind"]] += 1
        types[f"{doc['kind']}:{doc.get('doc_type') or 'law'}"] += 1
        per_kommun[doc.get("kommun_code") or "law"] += 1
        title, text = doc.get("title") or "", doc.get("text") or ""
        if doc.get("kommun_code"):
            kommuner.add(doc["kommun_code"])
            named = {code_of[m.group(1).lower()] for m in kommun_named.finditer(title + "\n" + text[:6000])}
            if named and doc["kommun_code"] not in named:
                elsewhere[f"{short.get(doc['kommun_code'])} -> {'/'.join(sorted(short[c] for c in named))}"] += 1
        if repair_mojibake(title) != title:  # what corpus.extract would still repair
            garbled.append(f"{doc['doc_id']}: {title[:70]}")
        if "org.mozilla.javascript" in text:
            junk.append(doc["doc_id"])
        if "�" in title or text.count("�") > 20:
            replaced.append(f"{doc['doc_id']}: {title[:60]} ({text.count(chr(0xfffd))} in the text)")
        if doc["doc_id"].startswith("pdf:") and doc["doc_id"] not in decided:
            undecided.append(f"{doc['doc_id']}: {title[:70]}")
        if doc.get("needs_ocr"):
            scanned[doc["doc_type"]] += 1
        elif not text.strip():
            empty.append(doc["doc_id"])
        elif doc["kind"] != "law" and len(text) > 200:
            by_text[(doc.get("kommun_code"), hash(" ".join(text.split())))].append(doc["doc_id"])
    print(f"  {sum(kinds.values())} documents {dict(kinds)}, {len(kommuner)} municipalities")
    report.check(not elsewhere, f"documents naming only other municipalities than their site's (shared administrations, "
                                f"neighbours' plans; filed under the site's): {sum(elsewhere.values())}",
                 [f"{pair}: {n}" for pair, n in elsewhere.most_common()], "WARN")
    report.check(not garbled, f"no garbled title (UTF-8 read as Latin-1): {len(garbled)}", garbled, "WARN")
    report.check(not replaced, f"no title or text with replacement characters (�): {len(replaced)}", replaced, "WARN")
    report.check(not junk, f"no script artefacts in page text (org.mozilla.javascript...): {len(junk)}", junk, "WARN")
    report.check(not undecided, f"every PDF judged by corpus.pdf_filter (features, classify, llm, classify, apply): "
                                f"{len(undecided)} are not", undecided, "WARN")
    duplicates = [ids for ids in by_text.values() if len(ids) > 1]
    report.check(not duplicates, f"no duplicate text within a municipality: {len(duplicates)} groups",
                 [" = ".join(ids[:3]) for ids in duplicates], "WARN")
    report.check(not empty, f"no document without text (other than scanned PDFs): {len(empty)}", empty, "WARN")
    total_scanned = sum(scanned.values())
    report.line("INFO", f"{total_scanned} scanned PDFs waiting for OCR (no text, invisible to search): {dict(scanned)}")
    report.summary["documents"] = {"count": sum(kinds.values()), "kinds": dict(kinds), "garbled": len(garbled),
                                   "replacement_chars": len(replaced), "duplicates": len(duplicates),
                                   "needs_ocr": total_scanned, "other_kommun": sum(elsewhere.values()),
                                   "types": dict(types), "needs_ocr_types": dict(scanned),
                                   "per_kommun": dict(per_kommun)}


def check_laws(report: Report) -> None:
    report.start("Statutes (law chunks)")
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for chunk in read_jsonl(CHUNKS_PATH):
        if chunk["kind"] == "law":
            by_doc[chunk["doc_id"]].append(chunk)
    raw = list(LAWS_DIR.glob("*.txt"))
    report.check(len(by_doc) == len(raw), f"{len(by_doc)} statutes chunked, {len(raw)} downloaded")
    backwards, gaps = [], []
    for doc_id, chunks in by_doc.items():
        chunks.sort(key=lambda c: c["chunk_index"])
        title = chunks[0]["title"]
        previous = None
        for chunk in chunks:
            key = (_number(chunk.get("chapter")), _number(chunk.get("paragraph")))
            # Sections only go forward; a "1 §" after "12 §" in the same chapter is a chapter heading the chunker missed
            if previous is not None and key < previous:
                backwards.append(f"{title}: {chunk['section']} after {previous_section}")
            previous, previous_section = key, chunk["section"]
        chapters = sorted({_number(c["chapter"])[0] for c in chunks if c.get("chapter")})
        if chapters:
            missing = sorted(set(range(1, chapters[-1] + 1)) - set(chapters))
            text = next((p.read_text(encoding="utf-8") for p in raw if title.split(" (")[0] in p.read_text(encoding="utf-8")[:300]), "")
            for number in missing:
                # A chapter may be repealed ("4 kap. har upphävts"); if the raw text has its heading, the chunker missed it
                if re.search(rf"^{number} ?[kK]ap\.(?!.*[Uu]pphävts)", text, re.M):
                    gaps.append(f"{title}: {number} kap. is in the raw text but has no chunk")
    report.check(not backwards, f"sections in order within each statute ({len(backwards)} go backwards)", backwards)
    report.check(not gaps, f"every chapter heading of the raw text has chunks ({len(gaps)} missing)", gaps)
    report.summary["laws"] = {"statutes": len(by_doc), "chunks": sum(len(c) for c in by_doc.values()),
                              "backwards": len(backwards), "missing_chapters": len(gaps)}


def check_index(report: Report) -> None:
    report.start(f"Index and store ({MODEL})")
    ids, docs, empty_header = set(), set(), 0
    duplicate_ids = 0
    for chunk in read_jsonl(CHUNKS_PATH):
        duplicate_ids += chunk["chunk_id"] in ids
        ids.add(chunk["chunk_id"])
        docs.add(chunk["doc_id"])
        empty_header += not chunk.get("header")
    report.check(not duplicate_ids, f"{len(ids)} chunks, unique ids ({duplicate_ids} duplicates)")
    report.check(not empty_header, f"every chunk has a context header ({empty_header} without)")
    known_docs = {doc["doc_id"] for doc in read_jsonl(DOCUMENTS_PATH)}
    orphan_chunks = docs - known_docs
    report.check(not orphan_chunks, f"every chunk's document is in documents.jsonl ({len(orphan_chunks)} not)",
                 sorted(orphan_chunks), "WARN")
    dense = INDEX_DIR / "dense" / MODEL / "ids.json"
    if dense.exists():
        vector_ids = set(json.loads(dense.read_text()))
        missing = ids - vector_ids
        report.check(not missing, f"every chunk has a vector ({len(missing)} missing: run localrag.index)", sorted(missing)[:6])
        report.line("INFO", f"{len(vector_ids - ids)} vectors of chunks no longer in the corpus (dropped by localrag.store)")
    else:
        report.line("ERROR", f"no dense index at {dense.parent}")
    store = INDEX_DIR / "store" / MODEL / "corpus.sqlite"
    if store.exists():
        db = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
        stored = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        db.close()
        report.check(stored == len(ids), f"the store has the chunks of chunks.jsonl ({stored} vs {len(ids)}: "
                     "rebuild with localrag.store, then restart the backend)")
    else:
        report.line("ERROR", f"no disk store at {store}")
    report.summary["index"] = {"chunks": len(ids)}


def check_plans(report: Report) -> None:
    report.start("Plan registry (plans.jsonl)")
    path = DATA_DIR / "plans.jsonl"
    if not path.exists():
        report.line("ERROR", "no plans.jsonl: run corpus.plans")
        return
    plans = list(read_jsonl(path))
    without = [p for p in plans if not p["documents"]]
    share = len(without) / max(len(plans), 1)
    # A plan known from a page of the municipality but none of its documents crawled: a coverage gap the
    # benchmarks cannot see (their cases come from documents in the corpus)
    report.check(share < 0.25, f"{len(plans)} plans, {len(without)} ({share:.0%}) without any document in the corpus",
                 [f"{p['kommun']}: {p['name'][:60]}" for p in without], "WARN")
    with_rules = sum(1 for p in plans if p["provisions"])
    report.line("INFO", f"{with_rules} plans with extracted provisions ({with_rules / max(len(plans), 1):.0%})")
    replaced = [p["name"] for p in plans if "�" in p["name"]]
    report.check(not replaced, f"no plan name with replacement characters ({len(replaced)})", replaced, "WARN")
    report.summary["plans"] = {"plans": len(plans), "without_documents": len(without), "with_provisions": with_rules,
                               "provisions": sum(len(p["provisions"]) for p in plans),
                               "status": dict(Counter(p.get("status") or "unknown" for p in plans)),
                               "documents_per_plan": dict(Counter(min(len(p["documents"]), 5) for p in plans))}


def main() -> None:
    sections = {"crawl": None, "documents": check_documents, "laws": check_laws, "index": check_index, "plans": check_plans}
    parser = argparse.ArgumentParser(description="Check the corpus after a rebuild")
    parser.add_argument("--only", nargs="*", choices=list(sections), help="sections to run (default: all)")
    parser.add_argument("--delete-orphan-pdfs", action="store_true", help="delete PDFs no crawl manifest references")
    args = parser.parse_args()

    previous = json.loads(CHECK_PATH.read_text(encoding="utf-8")) if CHECK_PATH.exists() else {}
    report = Report()
    crawl_yield = previous.get("crawl", {})
    for name in args.only or list(sections):
        if name == "crawl":
            crawl_yield = check_crawl(report, previous)
        else:
            sections[name](report)
    if args.delete_orphan_pdfs and report.summary.get("orphans"):
        from pathlib import Path
        for path in report.summary["orphans"]:
            Path(path).unlink(missing_ok=True)
        print(f"\nDeleted {len(report.summary['orphans'])} orphan PDFs")
    report.summary.pop("orphans", None)
    lines, summary = report.lines, report.summary
    if args.only:  # keep the other sections of the previous run
        ran = {line["section"] for line in lines}
        lines = [line for line in previous.get("lines", []) if line["section"] not in ran] + lines
        summary = {**previous.get("summary", {}), **summary}
    CHECK_PATH.write_text(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(), "crawl": crawl_yield,
                                      "summary": summary, "lines": lines,
                                      "errors": sum(line["level"] == "ERROR" for line in lines),
                                      "warnings": sum(line["level"] == "WARN" for line in lines)},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{report.errors} errors, {report.warnings} warnings -> {CHECK_PATH}")
    sys.exit(1 if report.errors else 0)


if __name__ == "__main__":
    main()
