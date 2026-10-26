"""place.plan_documents.fetch_plan_documents against a fake kommun site: the crawl manifest keeps its done line last."""

import json

import httpx

from place.plan_documents import fetch_plan_documents

DONE = {"done": True, "pages": 1, "pdfs": 0, "pdf_links": 3}
PAGE = ('<html><head><title>Detaljplan för Kvarnen</title></head><body><p>Planbeskrivning och plankarta.</p>'
        '<a href="/plan/REF-plankarta.pdf">Plankarta</a></body></html>')


def write_plans(geo_dir, refs):
    """A snapshot plan layer whose plans link to their page on the kommun site."""
    folder = geo_dir / "0380"
    folder.mkdir(parents=True)
    features = [{"type": "Feature", "geometry": None,
                 "properties": {"Aktbeteckning": ref, "UrlDokument": f"https://www.uppsala.se/plan/{ref}"}}
                for ref in refs]
    (folder / "plans.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}),
                                          encoding="utf-8")


def write_manifest(web_dir, entries):
    folder = web_dir / "0380"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.jsonl").write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")


def manifest(web_dir):
    return [json.loads(line) for line in (web_dir / "0380" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]


def fetch(tmp_path, requests):
    """One run against the fake site; each requested URL is appended to `requests`."""
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path.endswith(".pdf"):
            return httpx.Response(200, content=b"%PDF-1.7 fake")
        return httpx.Response(200, text=PAGE.replace("REF", request.url.path.rsplit("/", 1)[-1]))
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return fetch_plan_documents("0380", client=client, web_dir=tmp_path / "web", geo_dir=tmp_path / "geo", delay=0)


def test_new_entries_go_before_the_done_line(tmp_path):
    """corpus.crawl --revisit reads the last line: the plans' pages and PDFs are added before it."""
    write_plans(tmp_path / "geo", ["0380-P1", "0380-P2"])
    write_manifest(tmp_path / "web", [{"type": "page", "id": "home", "url": "https://www.uppsala.se/"}, DONE])
    counts = fetch(tmp_path, [])
    lines = manifest(tmp_path / "web")
    assert (counts["plans"], counts["pdfs"]) == (2, 2)
    assert lines[-1] == DONE
    assert [line["type"] for line in lines[:-1]] == ["page", "page", "pdf", "page", "pdf"]


def test_a_done_line_left_in_the_middle_moves_to_the_end(tmp_path):
    """A manifest from the earlier version, which appended after the done line, is repaired."""
    write_plans(tmp_path / "geo", [])
    write_manifest(tmp_path / "web", [{"type": "page", "id": "home"}, DONE, {"type": "page", "id": "plan"}])
    fetch(tmp_path, [])
    lines = manifest(tmp_path / "web")
    assert lines[-1] == DONE
    assert [line["id"] for line in lines[:-1]] == ["home", "plan"]


def test_a_second_run_fetches_nothing(tmp_path):
    """Plans already in plan_pages.json and in the manifest are skipped, and nothing is recorded twice."""
    write_plans(tmp_path / "geo", ["0380-P1"])
    write_manifest(tmp_path / "web", [DONE])
    fetch(tmp_path, [])
    before = manifest(tmp_path / "web")
    requests = []
    assert fetch(tmp_path, requests)["plans"] == 0
    assert requests == []
    assert manifest(tmp_path / "web") == before


def test_a_plan_missing_from_a_rewritten_manifest_is_recorded_again(tmp_path):
    """After a crawl --force rewrote the manifest, the plan's page is read again; its PDF on disk is not downloaded."""
    write_plans(tmp_path / "geo", ["0380-P1"])
    write_manifest(tmp_path / "web", [DONE])
    fetch(tmp_path, [])
    write_manifest(tmp_path / "web", [DONE])
    requests = []
    fetch(tmp_path, requests)
    assert requests == ["https://www.uppsala.se/plan/0380-P1"]
    assert [line.get("type") for line in manifest(tmp_path / "web")] == ["page", "pdf", None]
