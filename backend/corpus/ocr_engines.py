"""
OCR engines, for the benchmark (corpus.ocr_bench) and for the corpus (corpus.ocr). Standalone (no corpus imports):
run it with the Python environment that has the engine. Large images (plankartor) are cut into overlapping tiles; a
word belongs to the tile whose core holds its centre, so tiles do not duplicate words.

Benchmark: writes data/ocr_bench/pred-<engine>.jsonl, one line per image:
{"id", "seconds", "words": [[x0, y0, x1, y1, text, score], ...], "word_boxes": "native" | "split"}.

    cd backend
    .venv-ocr/Scripts/python corpus/ocr_engines.py --engine rapid-v6-small --gpu   # PP-OCRv6 via RapidOCR (ONNX)
    .venv-ocr/Scripts/python corpus/ocr_engines.py --engine rapid-v6-medium --gpu
    .venv/Scripts/python corpus/ocr_engines.py --engine easyocr --gpu             # the engine used before (sv + en)

Corpus (`--jobs <file>`, written by corpus.ocr): one JSON per scanned PDF with the text of each page in reading order
and every word with its box in PDF coordinates (unrotated, like PyMuPDF's get_text("words"): view_map_area can find
a property label on a scan); outputs already made by this engine are skipped (resumable).

--gpu: EasyOCR on CUDA (torch of .venv); PP-OCRv6 on DirectML (onnxruntime-directml, Windows' GPU API: 0.75 s per
2000 px tile with word boxes on the RTX 4060, 4.8 s on the CPU). onnxruntime-gpu (CUDA) failed on the recognition
model: cuDNN errors with the CUDA 13 build, an illegal memory access in QuickGelu with the CUDA 12 one.

.venv-ocr: `uv venv .venv-ocr --python 3.12 && uv pip install --python .venv-ocr/Scripts/python.exe rapidocr
onnxruntime-directml pymupdf` (kept apart from .venv, whose torch is the CUDA build the embeddings need).
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

BENCH_DIR = Path(__file__).resolve().parent.parent / "data" / "ocr_bench"
Image.MAX_IMAGE_PIXELS = None  # plankartor rendered at 200 dpi reach 40-60 Mpx
MAX_SIDE = 12000  # pixels: an A0 plankarta at 300 dpi is 14000 px


def tiles(height: int, width: int, size: int, overlap: int):
    """(top, left, core) per tile; core = the part of the tile whose words it keeps."""
    rows = list(range(0, max(height - overlap, 1), size - overlap))
    cols = list(range(0, max(width - overlap, 1), size - overlap))
    half = overlap // 2
    for i, top in enumerate(rows):
        for j, left in enumerate(cols):
            core = (left + (half if j else 0), top + (half if i else 0),
                    left + size - (half if j < len(cols) - 1 else 0), top + size - (half if i < len(rows) - 1 else 0))
            yield top, left, core


def split_line(points, text: str, score: float) -> list[list]:
    """Word boxes for an engine that returns lines: the line box cut in proportion to the characters."""
    xs, ys = [float(p[0]) for p in points], [float(p[1]) for p in points]  # EasyOCR gives numpy ints
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    words, total, position = text.split(), max(len(text), 1), 0
    out = []
    for word in words:
        start = text.index(word, position)
        position = start + len(word)
        out.append([x0 + (x1 - x0) * start / total, y0, x0 + (x1 - x0) * position / total, y1, word, score])
    return out


def box(points) -> list[float]:
    xs, ys = [float(p[0]) for p in points], [float(p[1]) for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def rapid_engine(model_type: str, gpu: bool, threads: int):
    from rapidocr import ModelType, OCRVersion, RapidOCR

    engine = RapidOCR(params={
        "Global.return_word_box": True, "Global.max_side_len": 4000, "Global.log_level": "warning",
        "Det.ocr_version": OCRVersion.PPOCRV6, "Det.model_type": ModelType(model_type),
        "Rec.ocr_version": OCRVersion.PPOCRV6, "Rec.model_type": ModelType(model_type),
        "Rec.rec_batch_num": 32,  # 6 by default: 25 % slower on map tiles (~100 lines each)
        "EngineConfig.onnxruntime.use_dml": gpu, "EngineConfig.onnxruntime.intra_op_num_threads": threads,
    })

    def run(image: np.ndarray) -> tuple[list[list], list[list], str]:
        result = engine(image)
        words, lines = [], []
        if result.txts is None:
            return words, lines, "native"
        for line, line_text, line_score, line_box in zip(result.word_results, result.txts, result.scores, result.boxes):
            lines.append([*box(line_box), line_text])
            # Word boxes come from the recogniser's character positions; a line without them is split evenly
            if line and all(item[2] is not None for item in line):
                for text, score, points in line:
                    words.append([*box(points), text, float(score)])
            else:
                words.extend(split_line(line_box, line_text, float(line_score)))
        return words, lines, "native"

    return run


def easyocr_engine(gpu: bool, threads: int):
    import torch

    if threads > 0:
        torch.set_num_threads(threads)
    import easyocr

    reader = easyocr.Reader(["sv", "en"], gpu=gpu, verbose=False)

    def run(image: np.ndarray) -> tuple[list[list], list[list], str]:
        words, lines = [], []
        for points, text, score in reader.readtext(image, paragraph=False):
            lines.append([*box(points), text])
            words.extend(split_line(points, text, float(score)))
        return words, lines, "split"

    return run


ENGINES = {
    "rapid-v6-tiny": lambda gpu, threads: rapid_engine("tiny", gpu, threads),
    "rapid-v6-small": lambda gpu, threads: rapid_engine("small", gpu, threads),
    "rapid-v6-medium": lambda gpu, threads: rapid_engine("medium", gpu, threads),
    "easyocr": easyocr_engine,
}


def ocr_image(run, image: np.ndarray, tile: int, overlap: int) -> tuple[list[list], list[list], str]:
    """Words [x0, y0, x1, y1, text, score] and lines [x0, y0, x1, y1, text] of a whole image, tile by tile."""
    words, lines, kind = [], [], "native"
    for top, left, core in tiles(*image.shape[:2], tile, overlap):
        found, found_lines, kind = run(np.ascontiguousarray(image[top:top + tile, left:left + tile]))
        inside = lambda x0, y0, x1, y1: core[0] <= (x0 + x1) / 2 < core[2] and core[1] <= (y0 + y1) / 2 < core[3]
        for x0, y0, x1, y1, text, score in found:
            if inside(x0 + left, y0 + top, x1 + left, y1 + top):
                words.append([x0 + left, y0 + top, x1 + left, y1 + top, text, score])
        for x0, y0, x1, y1, text in found_lines:
            if inside(x0 + left, y0 + top, x1 + left, y1 + top):
                lines.append([x0 + left, y0 + top, x1 + left, y1 + top, text])
    return words, lines, kind


def reading_order(lines: list[list]) -> str:
    """Lines grouped into rows (a line whose centre is below the current row starts the next one), left to right.
    Two-column pages interleave their columns; a map has no reading order anyway."""
    rows, current = [], []
    for line in sorted(lines, key=lambda l: (l[1] + l[3]) / 2):
        if current and (line[1] + line[3]) / 2 > max(l[3] for l in current):
            rows.append(current)
            current = []
        current.append(line)
    if current:
        rows.append(current)
    return "\n".join(" ".join(l[4] for l in sorted(row, key=lambda l: l[0])) for row in rows)


def ocr_pdf(run, path: str, max_pages: int, dpi: int, map_dpi: int, tile: int, overlap: int) -> dict:
    """Text per page and words in PDF coordinates. Pages larger than A3 (plankartor) are rendered at map_dpi.
    On the benchmark's real scans (2026-10-23), 300 instead of 200 dpi: map crops 83 vs 87 % of the words, the
    typewritten page 84 vs 73 % (one page only): text pages 300, maps 200."""
    import pymupdf

    pages, words = [], []
    with pymupdf.open(path) as pdf:
        for number, page in enumerate(list(pdf)[:max_pages]):
            wanted = map_dpi if max(page.rect.width, page.rect.height) > 1200 else dpi
            scale = min(wanted / 72, MAX_SIDE / max(page.rect.width, page.rect.height))
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False)
            image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3)
            found, lines, _ = ocr_image(run, image, tile, overlap)
            pages.append(reading_order(lines))
            # Pixels of the rendered (rotated) page -> PDF coordinates of the unrotated page
            back = pymupdf.Matrix(1 / scale, 1 / scale) * page.derotation_matrix
            for x0, y0, x1, y1, text, score in found:
                rect = pymupdf.Rect(x0, y0, x1, y1) * back
                words.append([number, round(rect.x0, 1), round(rect.y0, 1), round(rect.x1, 1), round(rect.y1, 1), text,
                              round(score, 3)])
    return {"pages": pages, "words": words}


def run_jobs(run, engine: str, args) -> None:
    jobs = [json.loads(line) for line in Path(args.jobs).open(encoding="utf-8")]
    done = 0
    for index, job in enumerate(jobs, 1):
        out = Path(job["out"])
        if out.exists():
            try:
                if json.loads(out.read_text(encoding="utf-8")).get("engine") == engine:
                    continue
            except ValueError:
                pass
        started = time.perf_counter()
        try:
            result = ocr_pdf(run, job["pdf"], job.get("max_pages", 40), args.dpi, args.map_dpi, args.tile, args.overlap)
        except Exception as exc:  # a broken PDF must not stop a night of OCR
            print(f"[{index}/{len(jobs)}] {job['pdf']}: {exc!r}", flush=True)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        temporary = out.with_suffix(".part")
        temporary.write_text(json.dumps({"engine": engine, "dpi": args.dpi, "map_dpi": args.map_dpi,
                                         "word_coordinates": "pdf points, unrotated page", **result},
                                        ensure_ascii=False), encoding="utf-8")
        temporary.replace(out)
        done += 1
        print(f"[{index}/{len(jobs)}] {job.get('label', '')[:70]}: {len(result['pages'])} pages, "
              f"{sum(len(p) for p in result['pages'])} chars, {len(result['words'])} words, "
              f"{time.perf_counter() - started:.0f}s", flush=True)
    print(f"{done} PDFs OCRed")


def run_bench(run, args) -> None:
    references = [json.loads(line) for line in (BENCH_DIR / "reference.jsonl").open(encoding="utf-8")]
    if args.ids:
        references = [r for r in references if r["id"] in set(args.ids)]
    suffix = ("-gpu" if args.gpu else "") + (f"-x{args.scale:g}" if args.scale != 1 else "")
    out = BENCH_DIR / f"pred-{args.engine}{suffix}.jsonl"
    with out.open("w", encoding="utf-8") as handle:
        for index, reference in enumerate(references, 1):
            picture = Image.open(BENCH_DIR / reference["image"]).convert("RGB")
            started = time.perf_counter()
            if args.scale != 1:
                picture = picture.resize((round(picture.width * args.scale), round(picture.height * args.scale)),
                                         Image.Resampling.LANCZOS)
            found, _, kind = ocr_image(run, np.array(picture), args.tile, args.overlap)
            words = [[round(v / args.scale, 1) for v in (x0, y0, x1, y1)] + [text, round(score, 3)]
                     for x0, y0, x1, y1, text, score in found]
            seconds = time.perf_counter() - started
            handle.write(json.dumps({"id": reference["id"], "seconds": round(seconds, 2), "words": words,
                                     "word_boxes": kind}, ensure_ascii=False) + "\n")
            handle.flush()
            print(f"{index}/{len(references)} {reference['id']}: {len(words)} words, {seconds:.1f} s", flush=True)
    print(f"-> {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one OCR engine on the benchmark images or on corpus PDFs")
    parser.add_argument("--engine", required=True, choices=sorted(ENGINES))
    parser.add_argument("--tile", type=int, default=2000, help="tile size in pixels for large images")
    parser.add_argument("--overlap", type=int, default=200)
    parser.add_argument("--gpu", action="store_true", help="EasyOCR: CUDA; PP-OCRv6: DirectML")
    parser.add_argument("--threads", type=int, default=-1, help="CPU threads (-1 = all)")
    parser.add_argument("--ids", nargs="*", help="benchmark: only these image ids")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="benchmark: enlarge the images first (1.5 ~ 300 dpi); boxes are scaled back")
    parser.add_argument("--jobs", help="corpus: JSONL of {pdf, out, max_pages, label} (written by corpus.ocr)")
    parser.add_argument("--dpi", type=int, default=300, help="corpus: rendering of text pages")
    parser.add_argument("--map-dpi", type=int, default=200, help="corpus: rendering of pages larger than A3")
    args = parser.parse_args()

    run = ENGINES[args.engine](args.gpu, args.threads)
    if args.jobs:
        run_jobs(run, f"{args.engine}{' (DirectML)' if args.gpu and args.engine.startswith('rapid') else ''}", args)
    else:
        run_bench(run, args)


if __name__ == "__main__":
    main()
