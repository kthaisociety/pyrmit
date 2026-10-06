import json
import re
from pathlib import Path


class LawChunker:
    def __init__(self, max_chunk_chars: int = 2400):
        self.max_chunk_chars = max_chunk_chars
        self._chapter_pattern = re.compile(r"^(\d+)\s+kap\.\s*(.*)$", re.IGNORECASE)
        self._section_pattern = re.compile(r"^(\d+[a-zA-Z]?)\s*§\s*(.*)$")

    def _normalize_text(self, lines: list[str]) -> str:
        cleaned: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                cleaned.append("")
                continue
            cleaned.append(re.sub(r"\s+", " ", stripped))

        text = "\n".join(cleaned)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _split_long_text(self, text: str) -> list[str]:
        if len(text) <= self.max_chunk_chars:
            return [text]

        blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
        parts: list[str] = []
        current = ""

        for block in blocks:
            candidate = f"{current}\n\n{block}".strip() if current else block
            if len(candidate) <= self.max_chunk_chars:
                current = candidate
                continue

            if current:
                parts.append(current)
                current = ""

            if len(block) <= self.max_chunk_chars:
                current = block
                continue

            sentences = re.split(r"(?<=[.!?])\s+", block)
            sentence_acc = ""
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                sentence_candidate = f"{sentence_acc} {sentence}".strip() if sentence_acc else sentence
                if len(sentence_candidate) <= self.max_chunk_chars:
                    sentence_acc = sentence_candidate
                else:
                    if sentence_acc:
                        parts.append(sentence_acc)
                    if len(sentence) <= self.max_chunk_chars:
                        sentence_acc = sentence
                    else:
                        for idx in range(0, len(sentence), self.max_chunk_chars):
                            parts.append(sentence[idx:idx + self.max_chunk_chars])
                        sentence_acc = ""

            if sentence_acc:
                current = sentence_acc

        if current:
            parts.append(current)

        return parts

    def chunk_text(self, text: str, law_name: str) -> list[dict]:
        lines = text.splitlines()
        chunks: list[dict] = []

        current_chapter_num: str | None = None
        current_chapter_title: str | None = None
        current_section: str | None = None
        section_buffer: list[str] = []

        def flush_section() -> None:
            nonlocal section_buffer
            section_text = self._normalize_text(section_buffer)
            section_buffer = []
            if not section_text:
                return

            for part in self._split_long_text(section_text):
                chunks.append(
                    {
                        "chunk_index": len(chunks),
                        "law_name": law_name,
                        "chapter": current_chapter_num,
                        "chapter_title": current_chapter_title,
                        "section": current_section,
                        "content": part,
                    }
                )

        for raw_line in lines:
            line = raw_line.rstrip()
            chapter_match = self._chapter_pattern.match(line.strip())
            if chapter_match:
                flush_section()
                current_chapter_num = chapter_match.group(1)
                current_chapter_title = chapter_match.group(2).strip() or None
                current_section = None
                continue

            section_match = self._section_pattern.match(line.strip())
            if section_match:
                flush_section()
                current_section = section_match.group(1)
                first_line = section_match.group(2).strip()
                section_buffer = [first_line] if first_line else []
                continue

            if current_section is not None:
                section_buffer.append(line)

        flush_section()
        return chunks

    def chunk_file(self, input_path: Path, output_path: Path | None = None) -> list[dict]:
        law_name = input_path.stem
        text = input_path.read_text(encoding="utf-8")
        chunks = self.chunk_text(text=text, law_name=law_name)

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")

        return chunks
