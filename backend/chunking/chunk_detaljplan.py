import argparse
import json
import logging
import re
from pathlib import Path


class DetaljplanChunker:
    def __init__(self, max_chunk_chars: int = 1800):
        self.max_chunk_chars = max_chunk_chars
        self._header_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
        self._noise_patterns = [
            re.compile(r"^!\[.*\]\(.*\)(\(.*\))?$") ,
            re.compile(r"^---+$"),
            re.compile(r"^KAPITEL$", re.IGNORECASE),
            re.compile(r"^Arbetsmaterial$", re.IGNORECASE),
            re.compile(r"^WWW\.[A-Z0-9\.-]+$", re.IGNORECASE),
            re.compile(r"^[A-ZÅÄÖ\s\-\.,]+\d{2,}.*$"),
            re.compile(r"^(SAMHÄLLSBYGGNADSFÖRVALTNINGEN|TUNA TORG|TFN|FAX|SBF@).*$", re.IGNORECASE),
        ]
        self._toc_pattern = re.compile(r"^\d+(\.\d+)*\.?\s+.*\.{3,}\s*\d+$")

    def _is_noise(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        return any(pattern.match(stripped) for pattern in self._noise_patterns)

    def _normalize_paragraph(self, lines: list[str]) -> str:
        if not lines:
            return ""

        cleaned = []
        for line in lines:
            stripped = line.strip()
            if not stripped or self._is_noise(stripped):
                continue
            cleaned.append(stripped)

        if not cleaned:
            return ""

        if all(item.startswith("- ") for item in cleaned):
            return "\n".join(cleaned)

        return re.sub(r"\s+", " ", " ".join(cleaned)).strip()

    def _should_skip_paragraph(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        if re.fullmatch(r"\d+", stripped):
            return True
        if re.match(r"^\d+(\.\d+)*\.?\s+.+\s+\d+$", stripped) and len(stripped) < 180:
            return True
        if self._toc_pattern.match(stripped):
            return True
        if re.search(r"\.{3,}\s*\d+$", stripped):
            return True
        return False

    def _split_long_text(self, text: str) -> list[str]:
        if len(text) <= self.max_chunk_chars:
            return [text]

        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks: list[str] = []
        current = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= self.max_chunk_chars:
                current = candidate
                continue

            if current:
                chunks.append(current)
                current = sentence
            else:
                for i in range(0, len(sentence), self.max_chunk_chars):
                    chunks.append(sentence[i:i + self.max_chunk_chars])
                current = ""

        if current:
            chunks.append(current)

        return chunks

    def chunk_markdown(self, markdown_text: str) -> list[dict]:
        lines = markdown_text.splitlines()

        chunks: list[dict] = []
        paragraph_buffer: list[str] = []
        header_stack: list[tuple[int, str]] = []

        def current_section() -> str:
            if not header_stack:
                return "Document"
            return " > ".join(text for _, text in header_stack)

        def flush_paragraph() -> None:
            paragraph = self._normalize_paragraph(paragraph_buffer)
            paragraph_buffer.clear()
            if not paragraph or self._should_skip_paragraph(paragraph):
                return

            section = current_section()
            for part in self._split_long_text(paragraph):
                if chunks and chunks[-1]["section"] == section and chunks[-1]["content"] == part:
                    continue
                chunks.append(
                    {
                        "chunk_index": len(chunks),
                        "section": section,
                        "content": part,
                    }
                )

        for raw_line in lines:
            line = raw_line.rstrip()

            if self._is_noise(line):
                continue

            header_match = self._header_pattern.match(line.strip())
            if header_match:
                flush_paragraph()
                level = len(header_match.group(1))
                text = re.sub(r"\s+\d+$", "", header_match.group(2).strip())

                while header_stack and header_stack[-1][0] >= level:
                    header_stack.pop()
                header_stack.append((level, text))
                continue

            if not line.strip():
                flush_paragraph()
                continue

            paragraph_buffer.append(line)

        flush_paragraph()
        return chunks

    def chunk_file(self, input_path: Path, output_path: Path | None = None) -> list[dict]:
        markdown_text = input_path.read_text(encoding="utf-8")
        chunks = self.chunk_markdown(markdown_text)

        if output_path:
            output_path.write_text(
                json.dumps(chunks, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return chunks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chunk detaljplan markdown by headers and paragraphs."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "output.md",
        help="Path to markdown file (default: backend/output.md)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "chunks.json",
        help="Path to output JSON (default: backend/chunks.json)",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=1800,
        help="Maximum characters per chunk.",
    )

    args = parser.parse_args()

    chunker = DetaljplanChunker(max_chunk_chars=args.max_chars)
    chunks = chunker.chunk_file(args.input, args.output)
    logging.info("Created %d chunks -> %s", len(chunks), args.output)


if __name__ == "__main__":
    main()

