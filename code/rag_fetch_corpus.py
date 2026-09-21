"""
HW3 Part 2, step 1 - download the corpus and write its documentation.

Reads the URL list in reports/hw03/urls.txt, downloads every page once,
keeps only the useful text, and saves one .txt file per page in
reports/hw03/corpus/. Then writes:
  reports/hw03/CORPUS_MANIFEST.json   file name, byte size, SHA-256, source URL
  reports/hw03/SOURCES.md             source URL and access date for every file

Two kinds of sources:
  - FDA company recall announcements (HTML pages on fda.gov)
  - 21 CFR Part 7 from the eCFR API (XML)

Run:   make fetch-corpus
       python code/rag_fetch_corpus.py --manifest-only   (re-hash existing files, no download)
"""
import argparse
import hashlib
import json
import re
import time
from datetime import date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
HW3 = ROOT / "reports" / "hw03"
URL_FILE = HW3 / "urls.txt"
CORPUS_DIR = HW3 / "corpus"
MANIFEST_FILE = HW3 / "CORPUS_MANIFEST.json"
SOURCES_FILE = HW3 / "SOURCES.md"
SOURCE_LIST_FILE = CORPUS_DIR / "_sources.json"   # file -> url, access date

MIN_CORPUS_BYTES = 200_000
HEADERS = {"User-Agent": "Mozilla/5.0 (DATA260 homework; corpus snapshot)"}


def clean(text):
    """Collapse all whitespace (newlines, tabs, repeated spaces) to one space,
    and drop the space get_text(" ") leaves before punctuation ("Listeria ." -> "Listeria.")."""
    text = " ".join(text.split())
    return re.sub(r" ([.,;:!?)])", r"\1", text).replace("( ", "(")


def read_urls():
    urls = []
    for line in URL_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def file_name_for(url):
    """fda.gov/.../gias-foods-inc-recalls-bettergoods-... -> fda_gias-foods-inc-recalls-bettergoods-authentic.txt"""
    if "ecfr.gov" in url:
        return "ecfr_21cfr_part7.txt"
    slug = url.rstrip("/").split("/")[-1]
    first_words = slug.split("-")[:6]
    return "fda_" + "-".join(first_words) + ".txt"


def fda_page_to_text(html):
    """Keep the title, the Summary box, and the company announcement text."""
    # "lxml" repairs broken HTML the way a browser does. Some FDA pages have
    # a <div> inside a <p>; Python's built-in "html.parser" then nests the whole
    # announcement inside that first <p> and most of the text gets lost.
    soup = BeautifulSoup(html, "lxml")
    lines = [clean(soup.find("h1").get_text(" ")), ""]

    anchor = soup.find("h2", id="recall-announcement")
    if anchor is None:
        raise ValueError("no 'Company Announcement' section on this page")

    # Summary box: Company Announcement Date, Company Name, Reason, ...
    summary = anchor.parent.find("dl")
    if summary is not None:
        for dt in summary.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            items = dd.select(".field--item")
            if items:
                value = "; ".join(clean(item.get_text(" ")) for item in items)
            else:
                value = clean(dd.get_text(" "))
            label = clean(dt.get_text(" ")).rstrip(":")
            lines.append(f"{label}: {value}")
        lines.append("")

    # The announcement: every paragraph, list item and table row after the
    # heading, in page order, until the next <h2> ("Company Contact Information").
    previous = None
    for element in anchor.find_all_next(["h2", "h3", "h4", "p", "li", "tr"]):
        if element.name == "h2":
            break
        if element.name != "tr" and element.find_parent("table"):
            continue  # text inside a table is already taken row by row
        if element.name in ("p", "li") and element.find_parent("li"):
            continue  # already part of the outer list item

        if element.name == "tr":
            cells = [clean(c.get_text(" ")) for c in element.find_all(["th", "td"])]
            text = " | ".join(cells)
        elif element.name == "li":
            text = "- " + clean(element.get_text(" "))
        else:
            text = clean(element.get_text(" "))
        if not text or text == "-":
            continue

        if previous in ("tr", "li") and element.name != previous:
            lines.append("")  # blank line after a table or a list
        lines.append(text)
        if element.name not in ("tr", "li"):
            lines.append("")
        previous = element.name

    return "\n".join(lines).strip() + "\n"


def ecfr_xml_to_text(xml):
    """Keep section headings (HEAD) and paragraphs (P); skip authority/source notes."""
    soup = BeautifulSoup(xml, "xml")
    lines = []
    for element in soup.find_all(["HEAD", "P"]):
        if element.find_parent(["AUTH", "SOURCE"]):
            continue
        text = clean(element.get_text(" "))
        if text:
            lines.append(text)
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def download_all():
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    urls = read_urls()
    names = [file_name_for(u) for u in urls]
    if len(set(names)) != len(names):
        raise SystemExit("two URLs map to the same file name - fix file_name_for()")

    sources = {}
    failed = []
    for i, (url, name) in enumerate(zip(urls, names), start=1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            if "ecfr.gov" in url:
                text = ecfr_xml_to_text(response.text)
            else:
                text = fda_page_to_text(response.text)
        except Exception as err:
            print(f"[{i:2d}/{len(urls)}] FAILED {name}: {err}")
            failed.append(url)
            continue

        (CORPUS_DIR / name).write_text(text, encoding="utf-8")
        sources[name] = {"source_url": url, "accessed": date.today().isoformat()}
        print(f"[{i:2d}/{len(urls)}] {len(text.encode('utf-8')):6d} bytes  {name}")
        time.sleep(0.5)  # be polite to fda.gov

    SOURCE_LIST_FILE.write_text(json.dumps(sources, indent=2), encoding="utf-8")
    if failed:
        print(f"\n{len(failed)} download(s) failed - re-run, or remove them from urls.txt")


def sha256_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest_and_sources():
    sources = json.loads(SOURCE_LIST_FILE.read_text(encoding="utf-8"))
    files = []
    for path in sorted(CORPUS_DIR.glob("*.txt")):
        info = sources.get(path.name, {})
        files.append({
            "file": f"corpus/{path.name}",
            "bytes": path.stat().st_size,
            "sha256": sha256_of(path),
            "source_url": info.get("source_url", ""),
            "accessed": info.get("accessed", ""),
        })

    total = sum(f["bytes"] for f in files)
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "domain": "DOMAIN_ID 3 - Grocery supply and recall notices",
        "n_files": len(files),
        "total_bytes": total,
        "files": files,
    }
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    lines = [
        "# SOURCES - HW3 corpus",
        "",
        "Domain: DOMAIN_ID 3 - Grocery supply and recall notices.",
        "",
        "All files are local text snapshots made by `code/rag_fetch_corpus.py` from public pages:",
        "",
        "- FDA company recall announcements, listed at "
        "https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts "
        "(Product Type = Food & Beverages). Only the title, the Summary box and the "
        "announcement text are kept; menus, footers and photos are dropped.",
        "- 21 CFR Part 7 (Enforcement Policy, including Subpart C - Recalls) from the eCFR API, "
        "version dated 2026-09-17.",
        "",
        f"{len(files)} files, {total:,} bytes in total. Hashes are in CORPUS_MANIFEST.json.",
        "",
        "| # | Local file | Source URL | Accessed |",
        "|---|---|---|---|",
    ]
    for n, f in enumerate(files, start=1):
        lines.append(f"| {n} | `{f['file']}` | {f['source_url']} | {f['accessed']} |")
    SOURCES_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n{len(files)} files, {total:,} bytes -> {MANIFEST_FILE.name}, {SOURCES_FILE.name}")
    if total < MIN_CORPUS_BYTES:
        print(f"WARNING: corpus is smaller than {MIN_CORPUS_BYTES:,} bytes - add more URLs")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-only", action="store_true",
                        help="do not download; only re-hash the files already in corpus/")
    args = parser.parse_args()

    if not args.manifest_only:
        download_all()
    write_manifest_and_sources()
