"""
OCR benchmark: which engine reads the scanned plans best, and where each word is (view_map_area finds a property
label such as "5:125" on a plankarta by its position, which a scan only has after an OCR that keeps word boxes).

Two sets, in data/ocr_bench/ (images, not versioned); results in data/eval/ocr-<date>.json:
- synthetic: pages of PDFs that have a text layer (plankartor, planbeskrivningar), rendered at 200 dpi and degraded
  like a scan (blur, noise, JPEG); the text layer is the reference, words and boxes, so both are scored without
  annotation. These are newer plans than the scans: optimistic for old typefaces, handwriting, yellowed paper.
- real: crops of scanned PDFs (old plans), transcribed by hand in corpus/ocr_reference.jsonl (words only): the set
  that decides. `sample` renders the scanned pages with a preview (data/ocr_bench/preview/); a crop is added to
  ocr_reference.jsonl ({"id", "doc_id", "page", "crop": [x0, y0, x1, y1] in pixels of the 200-dpi page, "text"}),
  `crops` cuts it, then its text is transcribed.

Scores per engine and set: words found (exact and within one or two edits; bag of words, the reading order of a
map is undefined), property labels (\\d+:\\d+) found, and on the synthetic set words found at the right place
(same text, box overlap >= 0.3).

    python -m corpus.ocr_bench sample [--synthetic 30] [--real 30]
    python -m corpus.ocr_bench crops
    .venv-ocr/Scripts/python corpus/ocr_engines.py --engine rapid-v6-small     # see corpus/ocr_engines.py
    python -m corpus.ocr_bench score
"""

import argparse
import io
import json
import random
import re
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

from corpus.common import DOCUMENTS_PATH, RESULTS_ROOT, WEB_DIR, read_jsonl
from corpus.crawl import fold

BENCH_DIR = RESULTS_ROOT / "ocr_bench"
REFERENCE_PATH = Path(__file__).resolve().parent / "ocr_reference.jsonl"  # hand transcriptions (versioned)
EVAL_DIR = RESULTS_ROOT / "eval"
DPI = 200
MAX_SIDE = 7000  # A0 / A1 plankartor at 200 dpi: ~9000 px, capped
LABEL = re.compile(r"^\d+:\d+$")
LOOSE_LABEL = re.compile(r"^(\d+)[.,;:](\d+)$")


def pdf_path(doc_id: str) -> Path:
    _, code, pdf_id = doc_id.split(":")
    return WEB_DIR / code / "pdf" / f"{pdf_id}.pdf"


def candidates() -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {"synthetic_map": [], "synthetic_text": [], "real_map": [], "real_text": []}
    for doc in read_jsonl(DOCUMENTS_PATH):
        if doc["kind"] != "pdf":
            continue
        name = fold(f"{doc.get('title') or ''} {doc.get('url') or ''}")
        pages = doc.get("pages") or 0
        if not doc.get("needs_ocr"):
            if doc.get("doc_type") == "detaljplan" and "plankarta" in name and pages <= 2:
                groups["synthetic_map"].append(doc)
            elif "planbeskrivning" in name and pages >= 4:
                groups["synthetic_text"].append(doc)
        elif doc.get("doc_type") == "detaljplan" and pages == 1:
            groups["real_map"].append(doc)
        elif pages >= 3 and re.search(r"planbeskrivning|beskrivning|_pb\b|_pb\.pdf|planhandling", name):
            groups["real_text"].append(doc)
    return groups


def render(page, scale_cap: float = MAX_SIDE):
    import pymupdf

    scale = min(DPI / 72, scale_cap / max(page.rect.width, page.rect.height))
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False)
    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3)
    return image, scale


def degrade(image: np.ndarray, rng: random.Random) -> bytes:
    """A scan-like copy: grey, slightly blurred, noisy, JPEG-compressed."""
    from PIL import Image, ImageFilter

    grey = Image.fromarray(image).convert("L").filter(ImageFilter.GaussianBlur(rng.uniform(0.5, 1.1)))
    pixels = np.asarray(grey, dtype=np.float32)
    pixels += np.random.default_rng(rng.randrange(1 << 30)).normal(0, rng.uniform(4, 10), pixels.shape)
    buffer = io.BytesIO()
    Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8)).save(buffer, "JPEG", quality=rng.randint(35, 60))
    return buffer.getvalue()


def text_layer_words(page, scale: float) -> list[list]:
    import pymupdf

    # Word coordinates are unrotated; the rendering applies the page rotation
    matrix = page.rotation_matrix * pymupdf.Matrix(scale, scale)
    words = []
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        rect = pymupdf.Rect(x0, y0, x1, y1) * matrix
        words.append([round(rect.x0, 1), round(rect.y0, 1), round(rect.x1, 1), round(rect.y1, 1), text])
    return words


def sample(n_synthetic: int, n_real: int, seed: int = 7) -> None:
    import pymupdf
    from PIL import Image

    rng = random.Random(seed)
    groups = candidates()
    print({k: len(v) for k, v in groups.items()})
    (BENCH_DIR / "images").mkdir(parents=True, exist_ok=True)
    (BENCH_DIR / "preview").mkdir(parents=True, exist_ok=True)
    rows = []
    for group, wanted in (("synthetic_map", n_synthetic // 2), ("synthetic_text", n_synthetic - n_synthetic // 2),
                          ("real_map", n_real * 2 // 3), ("real_text", n_real - n_real * 2 // 3)):
        docs, kommuner, taken = groups[group][:], set(), 0
        rng.shuffle(docs)
        for doc in docs:
            if taken >= wanted:
                break
            if doc["kommun_code"] in kommuner or not pdf_path(doc["doc_id"]).exists():
                continue  # one document per kommun: layouts and scanners differ between kommuner
            try:
                pdf = pymupdf.open(pdf_path(doc["doc_id"]))
            except Exception:
                continue
            page_no = 0 if group.endswith("map") else rng.randrange(1, min(len(pdf), 10))
            page = pdf[page_no]
            kind, real = group.split("_")[1], group.startswith("real")
            image, scale = render(page)
            item = {"id": f"{group}-{taken:02d}", "set": "real" if real else "synthetic", "kind": kind,
                    "doc_id": doc["doc_id"], "title": doc.get("title", "")[:100], "page": page_no,
                    "width": image.shape[1], "height": image.shape[0]}
            if real:
                # The whole page, kept for cutting crops; a preview to choose them
                Image.fromarray(image).save(BENCH_DIR / "preview" / f"{item['id']}-full.jpg", quality=92)
                preview = Image.fromarray(image)
                preview.thumbnail((1600, 1600))
                preview.save(BENCH_DIR / "preview" / f"{item['id']}.jpg", quality=85)
                item["preview_scale"] = round(preview.width / image.shape[1], 5)
            else:
                words = text_layer_words(page, scale)
                if len(words) < 80:  # a map with little text: no reference worth scoring
                    continue
                (BENCH_DIR / "images" / f"{item['id']}.jpg").write_bytes(degrade(image, rng))
                item.update(image=f"images/{item['id']}.jpg", words=words)
            rows.append(item)
            kommuner.add(doc["kommun_code"])
            taken += 1
            print(f"{item['id']}: {doc['doc_id']} p{page_no} {image.shape[1]}x{image.shape[0]} {item['title'][:60]}")
    with (BENCH_DIR / "pages.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_reference()


def crops() -> None:
    """Cuts the hand-chosen crops of the real scans (ocr_reference.jsonl) out of the 200-dpi pages."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    pages = {p["doc_id"]: p for p in read_jsonl(BENCH_DIR / "pages.jsonl") if p["set"] == "real"}
    for ref in read_jsonl(REFERENCE_PATH):
        page = pages.get(ref["doc_id"])
        if page is None:
            print(f"{ref['id']}: page not sampled ({ref['doc_id']})")
            continue
        with Image.open(BENCH_DIR / "preview" / f"{page['id']}-full.jpg") as full:
            full.crop(tuple(ref["crop"])).save(BENCH_DIR / "images" / f"{ref['id']}.jpg", quality=95)
    write_reference()


def write_reference() -> None:
    """data/ocr_bench/reference.jsonl = the synthetic pages + the transcribed real crops (what the engines read)."""
    rows = [p for p in read_jsonl(BENCH_DIR / "pages.jsonl") if p["set"] == "synthetic"]
    if REFERENCE_PATH.exists():
        rows += [{"id": r["id"], "set": "real", "kind": r.get("kind", "map"), "doc_id": r["doc_id"],
                  "image": f"images/{r['id']}.jpg", "text": r["text"]}
                 for r in read_jsonl(REFERENCE_PATH) if r.get("text") and (BENCH_DIR / "images" / f"{r['id']}.jpg").exists()]
    with (BENCH_DIR / "reference.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{len(rows)} images in {BENCH_DIR / 'reference.jsonl'}")


# --- scoring ----------------------------------------------------------------------------------------------------

def norm(word: str) -> str:
    return word.strip(".,;:!?()[]{}\"'«»”“’‘-–—*").lower()


def edits(a: str, b: str, limit: int) -> int:
    """Levenshtein distance, stopped early above `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


def word_scores(reference: list[str], predicted: list[str]) -> dict:
    ref, pred = Counter(w for w in map(norm, reference) if w), Counter(w for w in map(norm, predicted) if w)
    exact = sum((ref & pred).values())
    # Near misses: a reference word left over matched to a left-over prediction within 1 edit (2 for long words)
    left_ref, left_pred = list((ref - pred).elements()), list((pred - ref).elements())
    by_length: dict[int, list[str]] = {}
    for word in left_pred:
        by_length.setdefault(len(word), []).append(word)
    near = 0
    for word in left_ref:
        limit = 2 if len(word) >= 8 else 1 if len(word) >= 4 else 0
        if not limit:
            continue
        for length in range(len(word) - limit, len(word) + limit + 1):
            pool = by_length.get(length, [])
            match = next((p for p in pool if edits(word, p, limit) <= limit), None)
            if match:
                pool.remove(match)
                near += 1
                break
    labels = [w for w in ref.elements() if LABEL.match(w)]
    label_found = sum((Counter(labels) & pred).values())
    # Engines often read the colon of "3:204" as a point or comma: a search could accept both forms
    lenient = Counter(LOOSE_LABEL.sub(r"\1:\2", w) for w in pred.elements())
    n_ref, n_pred = sum(ref.values()), sum(pred.values())
    return {"ref_words": n_ref, "pred_words": n_pred, "exact": exact, "near": exact + near,
            "labels": len(labels), "labels_found": label_found,
            "labels_lenient": sum((Counter(labels) & lenient).values())}


def iou(a, b) -> float:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def located(reference: list[list], predicted: list[list]) -> tuple[int, int]:
    """Reference words found with the same text at the right place (box overlap >= 0.3), and labels among them."""
    by_text: dict[str, list] = {}
    for box in predicted:
        by_text.setdefault(norm(box[4]), []).append(box)
    found = labels = 0
    for box in reference:
        text = norm(box[4])
        hit = next((p for p in by_text.get(text, []) if iou(box, p) >= 0.3), None)
        if text and hit:
            by_text[text].remove(hit)
            found += 1
            labels += bool(LABEL.match(text))
    return found, labels


def score() -> dict:
    references = {r["id"]: r for r in read_jsonl(BENCH_DIR / "reference.jsonl")}
    results = {}
    for path in sorted(BENCH_DIR.glob("pred-*.jsonl")):
        engine = path.stem.removeprefix("pred-")
        totals: dict[tuple, Counter] = {}
        for pred in read_jsonl(path):
            ref = references.get(pred["id"])
            if ref is None:
                continue
            words = [w[4] for w in pred["words"]]
            ref_words = [w[4] for w in ref["words"]] if ref["set"] == "synthetic" else ref["text"].split()
            row = Counter(word_scores(ref_words, words))
            row["images"], row["seconds"] = 1, pred["seconds"]
            if ref["set"] == "synthetic":
                row["located"], row["labels_located"] = located(ref["words"], pred["words"])
            for key in ((ref["set"], ref["kind"]), (ref["set"], "all")):
                totals.setdefault(key, Counter()).update(row)
        results[engine] = {f"{s}/{k}": dict(v) for (s, k), v in totals.items()}
    lines = [f"{'engine':22} {'set':16} {'img':>4} {'words':>6} {'recall':>7} {'+near':>6} {'prec':>6} "
             f"{'labels (. for :)':>16} {'placed':>7} {'s/img':>6}"]
    for engine, sets in results.items():
        for name, t in sorted(sets.items()):
            recall = t["exact"] / max(t["ref_words"], 1)
            lines.append(
                f"{engine:22} {name:16} {t['images']:4} {t['ref_words']:6} {recall:7.1%} "
                f"{t['near'] / max(t['ref_words'], 1):6.1%} {t['exact'] / max(t['pred_words'], 1):6.1%} "
                f"{t['labels_found']:3}({t.get('labels_lenient', 0):3})/{t['labels']:<4} "
                f"{format(t['located'] / max(t['ref_words'], 1), '7.1%') if 'located' in t else '      –'} "
                f"{t['seconds'] / t['images']:6.1f}")
    print("\n".join(lines))
    print("recall = reference words read exactly; +near = within 1-2 edits; prec = predicted words that are in the "
          "reference; labels = property labels (5:125) read (in brackets: also read as 5.125 / 5,125); placed = read "
          "at the right place (synthetic only)")
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    out = EVAL_DIR / f"ocr-{date.today():%Y%m%d}.json"
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"-> {out}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR benchmark on plan pages (see the module docstring)")
    parser.add_argument("command", choices=["sample", "crops", "score"])
    parser.add_argument("--synthetic", type=int, default=30)
    parser.add_argument("--real", type=int, default=30, help="scanned pages rendered for choosing crops")
    args = parser.parse_args()
    {"sample": lambda: sample(args.synthetic, args.real), "crops": crops, "score": score}[args.command]()


if __name__ == "__main__":
    main()
