import argparse
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger(__name__)

from chunking.ingest_pipeline import ingest_folder


def ingest_data_folder(
    data_dir: Path,
    markdown_output_dir: Path,
    max_chars: int,
    clear_existing_for_document: bool,
) -> None:
    result = ingest_folder(
        data_dir=data_dir,
        markdown_output_dir=markdown_output_dir,
        max_chars=max_chars,
        clear_existing_for_document=clear_existing_for_document,
    )

    if result["documents_processed"] == 0:
        logger.warning("No supported files found in %s", data_dir)
        return

    for item in result["items"]:
        source_name = Path(item["source_file"]).name
        logger.info("Ingested %s: inserted=%d, deleted=%d", source_name, item["inserted"], item["deleted"])

    logger.info(
        "Done. documents=%d inserted=%d deleted=%d",
        result["documents_processed"], result["total_inserted"], result["total_deleted"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest all files in chunking/data into document_chunks")
    parser.add_argument("--data-dir", type=Path, default=Path("chunking/data"))
    parser.add_argument("--markdown-output-dir", type=Path, default=Path("data/ocr_markdown"))
    parser.add_argument("--max-chars", type=int, default=1800)
    parser.add_argument("--keep-existing", action="store_true")
    args = parser.parse_args()

    ingest_data_folder(
        data_dir=args.data_dir,
        markdown_output_dir=args.markdown_output_dir,
        max_chars=args.max_chars,
        clear_existing_for_document=not args.keep_existing,
    )


if __name__ == "__main__":
    main()
