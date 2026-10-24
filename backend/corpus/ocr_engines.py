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
(`"text_from": "words"`: lines cut by a tile edge rebuilt from their words; older outputs kept them from both tiles
and are redone after their tier) and every word with its box in PDF coordinates (unrotated, like PyMuPDF's get_text("words"): view_map_area can find
a property label on a scan); outputs already made by this engine are skipped (resumable).

--gpu: EasyOCR on CUDA (torch of .venv); PP-OCRv6 on DirectML (onnxruntime-directml, Windows' GPU API: 0.75 s per
2000 px tile with word boxes on the RTX 4060, 4.8 s on the CPU). onnxruntime-gpu (CUDA) failed on the recognition
model: cuDNN errors with the CUDA 13 build, an illegal memory access in QuickGelu with the CUDA 12 one.

.venv-ocr: `uv venv .venv-ocr --python 3.12 && uv pip install --python .venv-ocr/Scripts/python.exe rapidocr
onnxruntime-directml pymupdf` (kept apart from .venv, whose torch is the CUDA build the embeddings need).
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

BENCH_DIR = Path(__file__).resolve().parent.parent / "data" / "ocr_bench"
Image.MAX_IMAGE_PIXELS = None  # plankartor rendered at 200 dpi reach 40-60 Mpx
MAX_SIDE = 12000  # pixels: an A0 plankarta at 300 dpi is 14000 px
# DirectML keeps the GPU buffers of every input shape it has run (recognition batches vary in width): one process
# grew from ~3 to 7 GB of the RTX 4060's 8 GB in 2 h (2026-10-24 night), then spilled into shared memory and read
# ~35 % fewer words per second. --recycle-pages exits with this code; corpus.ocr starts a fresh process
RECYCLE_EXIT = 3


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


def fp16_models(model_type: str) -> dict[str, str]:
    """float16 copies of the PP-OCRv6 det / rec models (the released ONNX files are float32), made once next to the
    environment: `uv pip install --python .venv-ocr/Scripts/python.exe onnx` and `--no-deps onnxconverter-common`
    (its dependencies would replace onnxruntime-directml)."""
    import onnx
    import rapidocr
    from onnxconverter_common import float16

    source, target = Path(rapidocr.__file__).parent / "models", Path(sys.prefix) / "fp16"
    paths = {}
    for task in ("det", "rec"):
        out = target / f"PP-OCRv6_{task}_{model_type}_fp16.onnx"
        if not out.exists():
            target.mkdir(exist_ok=True)
            model = float16.convert_float_to_float16(onnx.load(source / f"PP-OCRv6_{task}_{model_type}.onnx"),
                                                     keep_io_types=True)
            onnx.save(model, out)
        paths[task] = str(out)
    return paths


def use_cuda_dlls() -> None:
    """onnxruntime-gpu (CUDA 12 build) on Windows needs the CUDA 12 / cuDNN 9 DLLs: those torch ships in backend/.venv
    (OCR_CUDA_DLLS overrides the directory)."""
    import os

    directory = os.getenv("OCR_CUDA_DLLS") or str(Path(__file__).resolve().parent.parent / ".venv" / "Lib" /
                                                   "site-packages" / "torch" / "lib")
    os.add_dll_directory(directory)
    os.environ["PATH"] = directory + os.pathsep + os.environ["PATH"]


def _latin(text: str) -> bool:
    """Characters Swedish planning documents print: ASCII, Latin-1 / Extended (å ä ö é ü...), dashes, quotes, symbols."""
    return all(0x20 <= ord(c) < 0x7F or 0xA0 <= ord(c) <= 0x24F or 0x2010 <= ord(c) <= 0x205E
               or c in "€≤≥≈±×÷°²³½¼¾µ§№™®©√∞" for c in text)


def latin_rec_model(path: str) -> str:
    """The recognition model with its output layer cut to the Latin characters (~840 of 18,710: the multilingual model
    also reads Chinese, Japanese...). The (lines x steps x 18,710) probabilities, up to ~290 MB per batch, were copied
    to the CPU and scanned there, and on CUDA they filled the GPU. The character list in the model metadata is cut
    the same way, so RapidOCR decodes it as it is (class 0 = CTC blank, the last = space)."""
    import onnx
    from onnx import numpy_helper

    out = Path(sys.prefix) / "fast" / f"{Path(path).stem}_latin.onnx"
    if not out.exists():
        model = onnx.load(path)
        meta = {p.key: p for p in model.metadata_props}
        characters = meta["character"].value.splitlines()
        keep = [0] + [i + 1 for i, c in enumerate(characters) if _latin(c)] + [len(characters) + 1]
        weights = {i.name: i for i in model.graph.initializer}
        matmul, add = [n for n in model.graph.node if n.op_type in ("MatMul", "Add")][-2:]
        for name, axis in ((matmul.input[1], 1), (add.input[1], 0)):
            array = numpy_helper.to_array(weights[name])
            weights[name].CopyFrom(numpy_helper.from_array(np.take(array, keep, axis=axis), name))
        meta["character"].value = "\n".join(characters[i - 1] for i in keep[1:-1])
        model.graph.output[0].type.tensor_type.shape.dim[2].dim_value = len(keep)
        out.parent.mkdir(exist_ok=True)
        onnx.save(model, out)
    return str(out)


class FixedShapes:
    """onnxruntime-gpu on Windows (cuDNN 9) re-plans every convolution, ~3 s, whenever an input shape differs from the
    previous call (an earlier shape too): with text lines of every width, CUDA was 5-10x slower than DirectML. Each
    input is zero-padded to one of a few fixed shapes, each served by its own session (so each sees one shape), and the
    output is cropped back. RapidOCR pads the lines of a batch with zeros already."""

    REC_WIDTHS = (320, 480, 640, 960, 1280, 1920, 2560, 3840)

    def __init__(self, inner, kind: str, batch: int, side: int = 0):
        self.kind, self.batch, self.side = kind, batch, side
        self.path = inner.session._model_path
        options = inner.session.get_provider_options()
        self.providers = [(p, options.get(p, {})) for p in inner.session.get_providers()]
        self.sessions: dict = {}

    def _run(self, x: np.ndarray) -> np.ndarray:
        if x.shape not in self.sessions:
            import onnxruntime as ort

            self.sessions[x.shape] = ort.InferenceSession(self.path, providers=self.providers)
        session = self.sessions[x.shape]
        return session.run(None, {session.get_inputs()[0].name: x})[0]

    def __call__(self, x: np.ndarray) -> np.ndarray:
        rows, channels, height, width = x.shape
        if self.kind == "det":  # (1, 3, H, W) -> (1, 1, H, W) probability map
            size = max(self.side, -(-height // 32) * 32, -(-width // 32) * 32)
            padded = np.zeros((rows, channels, size, size), np.float32)
            padded[:, :, :height, :width] = x
            return self._run(padded)[:, :, :height, :width]
        # cls: (B, 3, 48, 192) -> (B, 2); rec: (B, 3, 48, W) -> (B, W / 8, characters)
        size = width if self.kind == "cls" else next((w for w in self.REC_WIDTHS if w >= width), -(-width // 640) * 640)
        padded = np.zeros((max(self.batch, rows), channels, height, size), np.float32)
        padded[:rows, :, :, :width] = x
        out = self._run(padded)[:rows]
        return out if self.kind == "cls" else out[:, :round(out.shape[1] * width / size)]


def speed_up_rapidocr(engine) -> None:
    """Two CPU steps of RapidOCR done in one vectorised pass each (same results): ~10 % of a page's time.
    - detection pre-processing: (x / 255 - 0.5) / 0.5 per pixel in numpy, in float64 (float64 mean / std) plus two
      copies -> cv2.dnn.blobFromImage (x * 2/255 - 1, NCHW float32, C++);
    - word boxes: each corner of each character mapped back to the page one by one (np.dot per point), then the
      4 corners ordered -> one matrix product per line; unordered corners (only their min / max are used here)."""
    import math
    import types

    import cv2
    from rapidocr.cal_rec_boxes.main import Direction
    from rapidocr.ch_ppocr_det.utils import DetPreProcess

    original_preprocess = DetPreProcess.__call__

    def preprocess(self, img: np.ndarray):  # TextDetector makes a new DetPreProcess per image: patched on the class
        if not (np.allclose(self.mean, 0.5) and np.allclose(self.std, 0.5)):
            return original_preprocess(self, img)
        resized = self.resize(img)
        if resized is None:
            return None
        return cv2.dnn.blobFromImage(resized, scalefactor=2 / 255, mean=(127.5, 127.5, 127.5), swapRB=False)

    DetPreProcess.__call__ = preprocess

    def reverse_rotate_crop_image(self, bbox_points, word_points_list, direction):
        if not word_points_list or len({len(points) for points in word_points_list}) != 1:
            return original(self, bbox_points, word_points_list, direction)
        left, top = int(np.min(bbox_points[:, 0])), int(np.min(bbox_points[:, 1]))
        bbox_points[:, 0] -= left
        bbox_points[:, 1] -= top
        width = int(np.linalg.norm(bbox_points[0] - bbox_points[1]))
        height = int(np.linalg.norm(bbox_points[0] - bbox_points[3]))
        target = np.array([[0, 0], [width, 0], [width, height], [0, height]], np.float32)
        _, inverse = cv2.invert(cv2.getPerspectiveTransform(bbox_points, target))
        points = np.asarray(word_points_list, np.float64).reshape(-1, 2)
        if direction == Direction.VERTICAL:  # s_rotate by -90 degrees around the origin, then shifted by the width
            angle = math.radians(-90)
            x, y = points[:, 0].copy(), points[:, 1].copy()
            points = np.stack([x * math.cos(angle) + y * math.sin(angle) + width,
                               y * math.cos(angle) - x * math.sin(angle)], axis=1)
        mapped = np.c_[points, np.ones(len(points))] @ inverse.T
        xy = (mapped[:, :2] / mapped[:, 2:3]).astype(int) + [left, top]  # int() truncates like the original
        return xy.reshape(len(word_points_list), -1, 2).tolist()

    calculator = engine.cal_rec_boxes
    original = type(calculator).reverse_rotate_crop_image
    calculator.reverse_rotate_crop_image = types.MethodType(reverse_rotate_crop_image, calculator)


def rapid_engine(model_type: str, gpu: bool, threads: int, fp16: bool = False, det_side: int = 0, cuda: bool = False,
                 latin: bool = True):
    """det_side: longest side of the detection input (0 = the whole tile, 2000 px). Detection takes ~40 % of a tile's
    time; recognition still reads the text crops at full resolution. cuda: onnxruntime-gpu (backend/.venv-ocr-cuda)
    instead of DirectML; float16 models run ~2x faster there (tensor cores), not on DirectML."""
    if cuda:
        use_cuda_dlls()
    from rapidocr import ModelType, OCRVersion, RapidOCR

    models = fp16_models(model_type) if fp16 else {}
    import rapidocr

    rec_model = models.get("rec") or str(Path(rapidocr.__file__).parent / "models" / f"PP-OCRv6_rec_{model_type}.onnx")
    engine = RapidOCR(params={
        **({"Det.limit_type": "max", "Det.limit_side_len": det_side} if det_side else {}),
        **({"EngineConfig.onnxruntime.use_cuda": True,
            # EXHAUSTIVE (RapidOCR's default) falls back on Windows and was 4x slower on detection
            "EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search": "HEURISTIC"} if cuda else {}),
        "Global.return_word_box": True, "Global.max_side_len": 4000, "Global.log_level": "warning",
        "Det.ocr_version": OCRVersion.PPOCRV6, "Det.model_type": ModelType(model_type),
        "Rec.ocr_version": OCRVersion.PPOCRV6, "Rec.model_type": ModelType(model_type),
        "Rec.rec_batch_num": 32,  # 6 by default: 25 % slower on map tiles (~100 lines each)
        "EngineConfig.onnxruntime.use_dml": gpu and not cuda, "EngineConfig.onnxruntime.intra_op_num_threads": threads,
        **({"Det.model_path": models["det"]} if fp16 else {}),
        "Rec.model_path": latin_rec_model(rec_model) if latin else rec_model,
    })
    engine._load_det_model(), engine._load_cls_model(), engine._load_rec_model()  # lazy otherwise
    speed_up_rapidocr(engine)
    if cuda:  # one input shape per session (FixedShapes)
        engine.text_det.session = FixedShapes(engine.text_det.session, "det", 1, det_side or 2016)
        engine.text_cls.session = FixedShapes(engine.text_cls.session, "cls", engine.text_cls.cls_batch_num)
        engine.text_rec.session = FixedShapes(engine.text_rec.session, "rec", engine.text_rec.rec_batch_num)

    def run(image: np.ndarray) -> tuple[list[list], list[list], str]:
        result = engine(image)
        words, lines = [], []
        if result.txts is None:
            return words, lines, "native"
        for number, (line, line_text, line_score, line_box) in enumerate(
                zip(result.word_results, result.txts, result.scores, result.boxes)):
            lines.append([*box(line_box), line_text])
            # Word boxes come from the recogniser's character positions; a line without them is split evenly.
            # Each word carries the number of its line (ocr_image rebuilds the lines cut by a tile edge)
            if line and all(item[2] is not None for item in line):
                for text, score, points in line:
                    words.append([*box(points), text, float(score), number])
            else:
                words.extend([*word, number] for word in split_line(line_box, line_text, float(line_score)))
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
        for number, (points, text, score) in enumerate(reader.readtext(image, paragraph=False)):
            lines.append([*box(points), text])
            words.extend([*word, number] for word in split_line(points, text, float(score)))
        return words, lines, "split"

    return run


ENGINES = {
    "rapid-v6-tiny": lambda gpu, threads, **kw: rapid_engine("tiny", gpu, threads, **kw),
    "rapid-v6-small": lambda gpu, threads, **kw: rapid_engine("small", gpu, threads, **kw),
    "rapid-v6-medium": lambda gpu, threads, **kw: rapid_engine("medium", gpu, threads, **kw),
    # float16 copies: no faster on DirectML (2026-10-24 benchmark), same accuracy
    "rapid-v6-small-fp16": lambda gpu, threads, **kw: rapid_engine("small", gpu, threads, fp16=True, **kw),
    "rapid-v6-medium-fp16": lambda gpu, threads, **kw: rapid_engine("medium", gpu, threads, fp16=True, **kw),
    "easyocr": easyocr_engine,
}


def ocr_image(run, image: np.ndarray, tile: int, overlap: int) -> tuple[list[list], list[list], str]:
    """Words [x0, y0, x1, y1, text, score] and lines [x0, y0, x1, y1, text] of a whole image, tile by tile. A line
    crossing a tile edge is cut in both tiles: each tile gives the line's words of its core (until 2026-10-24 the
    whole line was kept from both: "gäller bestämm iller bestämmelsen"), see join_cut_lines."""
    words, lines, kind = [], [], "native"
    for top, left, core in tiles(*image.shape[:2], tile, overlap):
        found, _, kind = run(np.ascontiguousarray(image[top:top + tile, left:left + tile]))
        kept = {}
        for x0, y0, x1, y1, text, score, number in found:
            word = [x0 + left, y0 + top, x1 + left, y1 + top, text, score]
            if core[0] <= (word[0] + word[2]) / 2 < core[2] and core[1] <= (word[1] + word[3]) / 2 < core[3]:
                words.append(word)
                kept.setdefault(number, []).append(word)
        lines.extend(kept.values())
    lines = [[min(w[0] for w in line), min(w[1] for w in line), max(w[2] for w in line), max(w[3] for w in line),
              " ".join(w[4] for w in line)] for line in join_cut_lines(lines)]
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


def _glue(left: str, right: str) -> str | None:
    """One word read from two tiles, each side cut by the tile edge: "Användningsgrä" + "vändningsgräns", or one
    side whole: "byggnads" + "byggnadsarea"."""
    if right in left or left in right:
        return max(left, right, key=len)
    for size in range(min(len(left), len(right)) - 1, 2, -1):
        if left.endswith(right[:size]):
            return left + right[size:]
    return None


def _overlap(a: list, b: list) -> bool:
    """The boxes of two words cover the same spot (over a third of the smaller one, both ways)."""
    return (min(a[2], b[2]) - max(a[0], b[0]) > min(a[2] - a[0], b[2] - b[0]) / 3
            and min(a[3], b[3]) - max(a[1], b[1]) > min(a[3] - a[1], b[3] - b[1]) / 3)


def join_cut_lines(lines: list[list[list]]) -> list[list[list]]:
    """Lines as lists of words [x0, y0, x1, y1, text, ...]. A word cut by a tile edge can be kept from both tiles
    ("byggnads" + "byggnadsarea", centres on either side of the middle of the overlap): a line whose first word
    covers the last word of another line is its continuation, glued on that word. Other pieces of a cut line stay
    separate lines on the same row (reading_order puts them side by side)."""
    lines = [list(line) for line in lines]
    ends = {}
    for index, line in enumerate(lines):
        ends.setdefault(round(line[-1][1] / 20), []).append(index)
    for index, line in enumerate(lines):
        if not line:
            continue
        first = line[0]
        key = round(first[1] / 20)
        other = next((i for k in (key - 1, key, key + 1) for i in ends.get(k, [])
                      if i != index and lines[i] and _overlap(lines[i][-1], first) and _glue(lines[i][-1][4], first[4])),
                     None)
        if other is not None:
            last = lines[other][-1]
            lines[other][-1] = [min(last[0], first[0]), min(last[1], first[1]), max(last[2], first[2]),
                                max(last[3], first[3]), _glue(last[4], first[4])]
            lines[other].extend(line[1:])
            lines[index] = []
    return [line for line in lines if line]


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
    shard, shards = map(int, args.shard.split("/"))
    done = pages = 0
    family = f'"engine": "{engine.split("-")[0]}-v6'.encode()
    for index, job in enumerate(jobs, 1):
        if (index - 1) % shards != shard:  # another worker's job (corpus.ocr --workers)
            continue
        out = Path(job["out"])
        # Any PP-OCRv6 output is kept (model size or detection setting changed between runs) once its cut lines are
        # joined (text_from); EasyOCR's are redone. Both keys are in the first bytes of the file
        if out.exists():
            with out.open("rb") as handle:
                head = handle.read(400)
            if head.startswith(b"{" + family) and b'"text_from"' in head:
                continue
        started = time.perf_counter()
        try:
            result = ocr_pdf(run, job["pdf"], job.get("max_pages", 40), args.dpi, args.map_dpi, args.tile, args.overlap)
        except Exception as exc:  # a broken PDF must not stop a night of OCR
            print(f"[{index}/{len(jobs)}] {job['pdf']}: {exc!r}", flush=True)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        temporary = out.with_suffix(".part")
        temporary.write_text(json.dumps({"engine": engine, "dpi": args.dpi, "map_dpi": args.map_dpi,
                                         "word_coordinates": "pdf points, unrotated page", "text_from": "words",
                                         **result},
                                        ensure_ascii=False), encoding="utf-8")
        temporary.replace(out)
        done += 1
        pages += len(result["pages"])
        print(f"[{index}/{len(jobs)}] {job.get('label', '')[:70]}: {len(result['pages'])} pages, "
              f"{sum(len(p) for p in result['pages'])} chars, {len(result['words'])} words, "
              f"{time.perf_counter() - started:.0f}s", flush=True)
        if args.recycle_pages and pages >= args.recycle_pages:
            print(f"{done} PDFs OCRed, {pages} pages: new process (GPU memory)", flush=True)
            sys.exit(RECYCLE_EXIT)
    print(f"{done} PDFs OCRed")


def run_bench(run, args) -> None:
    references = [json.loads(line) for line in (BENCH_DIR / "reference.jsonl").open(encoding="utf-8")]
    if args.ids:
        references = [r for r in references if r["id"] in set(args.ids)]
    suffix = (("-cuda" if args.cuda else "-gpu" if args.gpu else "") + (f"-x{args.scale:g}" if args.scale != 1 else "")
              + (f"-det{args.det_side}" if args.det_side else ""))
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
    parser.add_argument("--det-side", type=int, default=0,
                        help="PP-OCRv6: longest side of the detection input (0 = whole tile; 1280 is ~28 %% faster)")
    parser.add_argument("--cuda", action="store_true",
                        help="PP-OCRv6 on onnxruntime-gpu (run from backend/.venv-ocr-cuda) instead of DirectML")
    parser.add_argument("--shard", default="0/1", help="corpus: worker i of n takes every n-th job")
    parser.add_argument("--recycle-pages", type=int, default=0,
                        help=f"corpus: exit with code {RECYCLE_EXIT} after this many pages (corpus.ocr starts a new process)")
    args = parser.parse_args()

    options = ({"det_side": args.det_side} if args.det_side else {}) | ({"cuda": True} if args.cuda else {})
    run = ENGINES[args.engine](args.gpu, args.threads, **options)
    if args.jobs:
        device = " (CUDA)" if args.cuda else " (DirectML)" if args.gpu else ""
        label = f"{args.engine}{f' det {args.det_side}' if args.det_side else ''}{device if args.engine.startswith('rapid') else ''}"
        run_jobs(run, label, args)
    else:
        run_bench(run, args)


if __name__ == "__main__":
    main()
