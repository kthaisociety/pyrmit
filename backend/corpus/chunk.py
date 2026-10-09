"""
Split documents.jsonl into retrieval chunks (data/corpus/chunks.jsonl).

Laws: one chunk per paragraph (§), long ones split on paragraph boundaries. A chapter
heading is only recognised on a line of its own after a blank line ("4 kap. Reglering
med ..."), so cross-references wrapped onto a new line ("4 kap. miljöbalken") don't open
a chapter, which is what corrupted the chapter metadata of the database chunks.
Lettered paragraphs ("6 a §") are kept as their own chunks. Transitional provisions
(Övergångsbestämmelser) are dropped.

Other documents: packed into ~`--max-chars` chunks along paragraph boundaries, with a
one-paragraph overlap and the closest heading kept as `section`.

Every chunk carries a `header` (law/kommun, document title, section) prepended to the
text for embedding and BM25, so a chunk stays interpretable on its own.

    cd backend && python -m corpus.chunk
"""

import argparse
import hashlib
import re

from corpus.common import CHUNKS_PATH, DOCUMENTS_PATH, read_jsonl, stable_id, write_jsonl

_CHAPTER = re.compile(r"^(\d+ ?[a-z]?) kap\. ([A-ZÅÄÖ].*)$")
# A paragraph opens with "21 §" followed by a capital ("21 § I detaljplanen..."), "/" for
# version markers ("/Upphör att gälla .../") or a list; "21 § andra stycket" is a reference
_SECTION = re.compile(r"^(\d+ ?[a-z]?) §(?!§) ?([A-ZÅÄÖ/\d(].*)$", re.S)
_TRANSITIONAL = re.compile(r"^Övergångsbestämmelser\s*$", re.M)
# Words a wrapped line can end on but a heading cannot
_CONTINUATION_ENDINGS = {
    "av", "och", "eller", "i", "på", "för", "till", "som", "att", "med", "om", "enligt", "den", "det", "de",
    "en", "ett", "från", "vid", "under", "inom", "utan", "mot", "genom", "efter", "över", "samt", "så", "får",
    "ska", "skall", "är", "kan", "har", "inte", "denna", "detta", "dessa", "sådan", "sådana", "än", "när",
}


# Lines left over from PDF layout: URLs, file names, dot leaders of tables of contents
_NOISE = re.compile(r"^(www\.\S+|\S+\.(pdf|docx?)|[\d\s.,:/-]{1,12}|.*\.{6,}\s*\d*)$", re.I)


def rejoin(paragraphs: list[str]) -> list[str]:
    """Some consolidated texts put a blank line after every wrapped line: glue the pieces back."""
    joined: list[str] = []
    for paragraph in paragraphs:
        if joined:
            previous = joined[-1]
            last_word = previous.rsplit(" ", 1)[-1].lower()
            continues = (
                paragraph[:1].islower()
                or last_word in _CONTINUATION_ENDINGS
                or previous.endswith(("-", ","))
                or (not previous.endswith((".", ":", ";", "?", ")")) and not _SECTION.match(paragraph)
                    and not _CHAPTER.match(paragraph) and len(previous) > 60)
            )
            if continues and not re.match(r"^\d+\. ", paragraph):
                joined[-1] = f"{previous} {paragraph}"
                continue
        joined.append(paragraph)
    return joined


def is_heading(paragraph: str) -> bool:
    """Standalone headings inside a chapter, e.g. 'Bygglov för nybyggnad'."""
    return (
        "\n" not in paragraph
        and len(paragraph) < 90
        and not paragraph.rstrip().endswith((".", ",", ":", ";"))
        and paragraph[:1].isupper()
        and not _SECTION.match(paragraph)
    )


def split_long(text: str, max_chars: int) -> list[str]:
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    parts, current = [], ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > max_chars:
            parts.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        parts.append(current)
    # A single paragraph above max_chars is cut on sentence boundaries
    result = []
    for part in parts:
        while len(part) > max_chars * 1.5:
            cut = part.rfind(". ", 0, max_chars)
            cut = cut + 1 if cut > max_chars // 2 else max_chars
            result.append(part[:cut].strip())
            part = part[cut:].strip()
        result.append(part)
    return result


def law_chunks(document: dict, max_chars: int) -> list[dict]:
    text = document["text"]
    body_start = text.find("\n\n", text.find("Källa:")) if "Källa:" in text[:2000] else 0
    text = text[body_start:]
    transitional = _TRANSITIONAL.search(text)
    if transitional:
        text = text[:transitional.start()]
    # Statute lines are hard-wrapped: rejoin each paragraph on one line
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]
    paragraphs = rejoin([p for p in paragraphs if p])

    chunks, chapter, chapter_title, heading = [], None, None, None
    section, section_parts = None, []

    def flush():
        if section is None or not section_parts:
            return
        body = "\n\n".join(section_parts)
        label = f"{chapter} kap. {section} §" if chapter else f"{section} §"
        header = f"{document['title']}, {label}"
        context = " – ".join(filter(None, [f"{chapter} kap. {chapter_title}" if chapter else None, heading]))
        if context:
            header += f" ({context})"
        for part_index, part in enumerate(split_long(f"{section} § {body}", max_chars)):
            chunks.append({
                "section": label,
                "chapter": chapter,
                "paragraph": section,
                "heading": heading,
                "part": part_index,
                "header": header,
                "text": part,
            })

    for index, paragraph in enumerate(paragraphs):
        chapter_match = _CHAPTER.match(paragraph)
        if chapter_match and len(paragraph) < 120:
            flush()
            chapter, chapter_title = chapter_match.group(1), chapter_match.group(2).strip()
            section, section_parts, heading = None, [], None
            continue
        section_match = _SECTION.match(paragraph)
        if section_match:
            flush()
            section, section_parts = section_match.group(1), [section_match.group(2).strip()]
            continue
        # A heading is followed by a paragraph (§); otherwise it is a sentence introducing a list
        following = paragraphs[index + 1] if index + 1 < len(paragraphs) else ""
        if is_heading(paragraph) and _SECTION.match(following):
            flush()
            heading, section, section_parts = paragraph.strip(), None, []
            continue
        if section is not None:
            section_parts.append(paragraph)
    flush()
    return chunks


def document_chunks(document: dict, max_chars: int) -> list[dict]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", document["text"]) if p.strip()]
    chunks, current, heading, previous = [], [], None, None
    place = document.get("kommun") or ""
    base_header = f"{place} kommun – {document['title']}" if place else document["title"]

    def flush():
        if not current:
            return
        text = "\n\n".join(current)
        if len(text) < 80 and chunks:  # tiny tail: merge into the previous chunk
            chunks[-1]["text"] += "\n\n" + text
            return
        chunks.append({
            "section": heading,
            "header": base_header + (f" – {heading}" if heading else ""),
            "text": text,
        })

    for paragraph in paragraphs:
        if _NOISE.match(paragraph):
            continue
        markdown_heading = re.match(r"^#{1,6}\s+(.*)$", paragraph)
        if markdown_heading or (is_heading(paragraph) and len(paragraph) < 70):
            flush()
            heading = (markdown_heading.group(1) if markdown_heading else paragraph).strip()
            current, previous = [], None
            continue
        for piece in split_long(paragraph, max_chars) if len(paragraph) > max_chars else [paragraph]:
            if current and sum(len(p) for p in current) + len(piece) > max_chars:
                flush()
                current = [previous] if previous and len(previous) < max_chars // 3 else []
            current.append(piece)
            previous = piece
    flush()
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk documents.jsonl into chunks.jsonl")
    parser.add_argument("--max-chars", type=int, default=1500)
    args = parser.parse_args()

    seen_hashes: set[str] = set()
    rows, duplicates = [], 0
    for document in read_jsonl(DOCUMENTS_PATH):
        if not document.get("text"):
            continue
        splitter = law_chunks if document["kind"] == "law" else document_chunks
        for index, chunk in enumerate(splitter(document, args.max_chars)):
            # The same PDF is often linked from several pages or kommuner: keep one copy
            digest = hashlib.sha1(" ".join(chunk["text"].split()).lower().encode()).hexdigest()
            if digest in seen_hashes:
                duplicates += 1
                continue
            seen_hashes.add(digest)
            rows.append({
                "chunk_id": stable_id(document["doc_id"], str(index), digest),
                "doc_id": document["doc_id"],
                "chunk_index": index,
                "kind": document["kind"],
                "doc_type": document["doc_type"],
                "kommun_code": document.get("kommun_code"),
                "kommun": document.get("kommun"),
                "title": document["title"],
                "url": document.get("url"),
                **chunk,
            })
    count = write_jsonl(CHUNKS_PATH, rows)
    laws = sum(1 for row in rows if row["kind"] == "law")
    print(f"{count} chunks ({laws} law, {count - laws} other), {duplicates} duplicates dropped -> {CHUNKS_PATH}")


if __name__ == "__main__":
    main()
