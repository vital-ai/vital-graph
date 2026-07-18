#!/usr/bin/env python3
"""
Fetch Wikipedia articles and convert them to markdown for segmentation testing.

Uses the Wikipedia REST API (no authentication required) to download article
HTML, then converts to clean markdown with heading sections suitable for the
markdown heading segmenter (urn:segmethod:markdown_heading_split).

Output files are written to test_files/wikipedia/ as .md files.

Usage:
    python test_scripts/data/fetch_wikipedia_test_docs.py

Articles can be customised by editing the ARTICLES list below.
"""

import argparse
import html
import json
import os
import re
import sys
import textwrap
import time
import urllib.request
import urllib.error
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Wikipedia articles to fetch.  Each entry is (page_title, output_filename).
# page_title must match the URL slug on en.wikipedia.org.
ARTICLES: List[Tuple[str, str]] = [
    ("Artificial_intelligence", "artificial_intelligence.md"),
    ("Solar_System", "solar_system.md"),
    ("History_of_New_York_City", "history_of_new_york_city.md"),
    ("Coffee", "coffee.md"),
    ("Python_(programming_language)", "python_programming_language.md"),
]

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "test_files" / "wikipedia"

# Wikipedia REST API endpoint (returns article HTML)
WIKI_API = "https://en.wikipedia.org/api/rest_v1/page/html/{title}"

# Also fetch mobile-sections-remaining for cleaner section data
WIKI_SECTIONS_API = "https://en.wikipedia.org/api/rest_v1/page/mobile-sections/{title}"

# Action API for random articles (namespace 0 = main/articles)
WIKI_RANDOM_API = (
    "https://en.wikipedia.org/w/api.php?action=query&format=json"
    "&list=random&rnnamespace=0&rnlimit={limit}"
)


def _slug(title: str) -> str:
    """Filesystem-safe .md filename from an article title."""
    s = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_").lower()
    return (s or "article")[:80] + ".md"


def fetch_random_titles(n: int) -> List[str]:
    """Return n random main-namespace article titles (URL slug form)."""
    titles: List[str] = []
    seen = set()
    while len(titles) < n:
        limit = min(50, n - len(titles) + 5)  # over-request to cover dupes
        url = WIKI_RANDOM_API.format(limit=limit)
        req = urllib.request.Request(url, headers={
            "User-Agent": "VitalGraph-TestDataFetcher/1.0 (test data generation)",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("query", {}).get("random", []):
            t = item["title"].replace(" ", "_")
            if t not in seen:
                seen.add(t)
                titles.append(t)
            if len(titles) >= n:
                break
        time.sleep(0.2)
    return titles[:n]


# ---------------------------------------------------------------------------
# HTML → Markdown converter (minimal, purpose-built)
# ---------------------------------------------------------------------------

class WikiHTMLToMarkdown(HTMLParser):
    """
    Lightweight HTML-to-Markdown converter for Wikipedia article HTML.

    Handles: headings (h1-h6), paragraphs, lists (ul/ol/li), bold, italic,
    links, blockquotes, pre/code, and tables (simplified).

    Strips: references, edit links, infoboxes, navigation boxes, images,
    style/script tags, and other non-content elements.
    """

    # Tags whose content should be completely suppressed
    _SKIP_TAGS = frozenset([
        "style", "script", "sup", "sub", "figure", "figcaption",
        "math", "annotation", "semantics",
    ])

    # CSS classes that indicate non-content elements to skip
    _SKIP_CLASSES = frozenset([
        "reflist", "reference", "references", "mw-references-wrap",
        "navbox", "navbox-inner", "sidebar", "infobox", "metadata",
        "noprint", "mw-editsection", "mw-jump-link", "toc", "catlinks",
        "mw-heading-indicator", "shortdescription", "mbox-small",
        "ambox", "tmbox", "ombox", "cmbox", "fmbox", "dmbox",
        "hatnote", "navigation-not-searchable",
    ])

    def __init__(self):
        super().__init__()
        self._output: List[str] = []
        self._skip_depth = 0       # depth inside skipped elements
        self._tag_stack: List[str] = []
        self._list_depth = 0
        self._list_type_stack: List[str] = []  # "ul" or "ol"
        self._ol_counters: List[int] = []
        self._in_pre = False
        self._in_table = False
        self._table_row: List[str] = []
        self._table_header = False
        self._current_cell: List[str] = []
        self._in_cell = False

    def _should_skip(self, tag: str, attrs: dict) -> bool:
        if tag in self._SKIP_TAGS:
            return True
        classes = set(attrs.get("class", "").split())
        if classes & self._SKIP_CLASSES:
            return True
        # Skip elements with role="navigation" or role="note"
        role = attrs.get("role", "")
        if role in ("navigation", "note", "presentation"):
            return True
        return False

    def handle_starttag(self, tag: str, attrs_list):
        attrs = dict(attrs_list)

        if self._should_skip(tag, attrs):
            self._skip_depth += 1
            return

        if self._skip_depth > 0:
            self._skip_depth += 1
            return

        self._tag_stack.append(tag)

        # Headings
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self._output.append(f"\n\n{'#' * level} ")

        # Paragraphs
        elif tag == "p":
            self._output.append("\n\n")

        # Lists
        elif tag in ("ul", "ol"):
            self._list_depth += 1
            self._list_type_stack.append(tag)
            if tag == "ol":
                self._ol_counters.append(0)

        elif tag == "li":
            indent = "  " * (self._list_depth - 1)
            if self._list_type_stack and self._list_type_stack[-1] == "ol":
                self._ol_counters[-1] += 1
                self._output.append(f"\n{indent}{self._ol_counters[-1]}. ")
            else:
                self._output.append(f"\n{indent}- ")

        # Inline formatting
        elif tag in ("b", "strong"):
            self._output.append("**")
        elif tag in ("i", "em"):
            self._output.append("*")
        elif tag == "a":
            pass  # Handle link text in data, ignore href
        elif tag == "br":
            self._output.append("\n")

        # Block elements
        elif tag == "blockquote":
            self._output.append("\n\n> ")
        elif tag in ("pre", "code"):
            if tag == "pre":
                self._in_pre = True
                self._output.append("\n\n```\n")

        # Tables (simplified — flatten to text)
        elif tag == "table":
            self._in_table = True
        elif tag == "tr" and self._in_table:
            self._table_row = []
        elif tag in ("th", "td") and self._in_table:
            self._in_cell = True
            self._current_cell = []
            self._table_header = (tag == "th")

    def handle_endtag(self, tag: str):
        if self._skip_depth > 0:
            self._skip_depth -= 1
            return

        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._output.append("\n\n")
        elif tag == "p":
            pass  # paragraph close is fine
        elif tag in ("ul", "ol"):
            self._list_depth = max(0, self._list_depth - 1)
            if self._list_type_stack:
                popped = self._list_type_stack.pop()
                if popped == "ol" and self._ol_counters:
                    self._ol_counters.pop()
            self._output.append("\n")
        elif tag in ("b", "strong"):
            self._output.append("**")
        elif tag in ("i", "em"):
            self._output.append("*")
        elif tag == "pre":
            self._in_pre = False
            self._output.append("\n```\n")
        elif tag in ("th", "td") and self._in_table:
            self._in_cell = False
            cell_text = "".join(self._current_cell).strip()
            self._table_row.append(cell_text)
        elif tag == "tr" and self._in_table:
            if self._table_row:
                self._output.append("\n" + " | ".join(self._table_row))
        elif tag == "table":
            self._in_table = False
            self._output.append("\n")

    def handle_data(self, data: str):
        if self._skip_depth > 0:
            return

        text = data
        if not self._in_pre:
            # Collapse whitespace
            text = re.sub(r"\s+", " ", text)

        if self._in_cell:
            self._current_cell.append(text)
        else:
            self._output.append(text)

    def handle_entityref(self, name: str):
        char = html.unescape(f"&{name};")
        self.handle_data(char)

    def handle_charref(self, name: str):
        char = html.unescape(f"&#{name};")
        self.handle_data(char)

    def get_markdown(self) -> str:
        raw = "".join(self._output)
        # Clean up excessive blank lines
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        # Remove trailing whitespace per line
        lines = [line.rstrip() for line in raw.split("\n")]
        return "\n".join(lines).strip() + "\n"


def html_to_markdown(html_content: str) -> str:
    """Convert Wikipedia HTML to clean markdown."""
    parser = WikiHTMLToMarkdown()
    parser.feed(html_content)
    return parser.get_markdown()


# ---------------------------------------------------------------------------
# Wikipedia API helpers
# ---------------------------------------------------------------------------

def fetch_article_html(title: str, max_retries: int = 5) -> str:
    """Fetch article HTML from Wikipedia REST API, retrying on 429 with backoff."""
    url = WIKI_API.format(title=urllib.parse.quote(title, safe=""))
    req = urllib.request.Request(url, headers={
        "User-Agent": "VitalGraph-TestDataFetcher/1.0 (https://vital.ai; test data generation)",
        "Accept": "text/html; charset=utf-8; profile=\"https://www.mediawiki.org/wiki/Specs/HTML/2.1.0\"",
    })
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                backoff = 2 ** attempt  # 1, 2, 4, 8, 16s
                print(f"(429, backing off {backoff}s)", end=" ", flush=True)
                time.sleep(backoff)
                continue
            raise


def clean_markdown(md: str, title: str) -> str:
    """Post-process markdown: add title, remove empty sections, trim length."""
    lines = md.split("\n")
    cleaned = []

    # Ensure we have a top-level title
    has_h1 = any(line.startswith("# ") for line in lines)
    if not has_h1:
        # Convert underscores/hyphens in title back to spaces
        display_title = title.replace("_", " ")
        # Remove parenthetical disambiguation
        display_title = re.sub(r"\s*\(.*?\)\s*$", "", display_title)
        cleaned.append(f"# {display_title}\n")

    # Process lines
    prev_blank = False
    for line in lines:
        # Skip "[edit]" artifacts
        if line.strip() == "[edit]":
            continue

        is_blank = len(line.strip()) == 0

        # Don't stack blank lines
        if is_blank and prev_blank:
            continue

        cleaned.append(line)
        prev_blank = is_blank

    result = "\n".join(cleaned).strip() + "\n"

    # Remove sections that are just a heading with no content
    result = re.sub(r"(#{1,6}\s+[^\n]+)\n\n(?=#{1,6}\s+)", "", result)

    return result


def fetch_and_convert(title: str, output_path: Path) -> dict:
    """Fetch a Wikipedia article and save as markdown. Returns stats dict."""
    print(f"  Fetching: {title} ...", end=" ", flush=True)

    html_content = fetch_article_html(title)
    md = html_to_markdown(html_content)
    md = clean_markdown(md, title)

    # Compute stats
    word_count = len(md.split())
    heading_count = len(re.findall(r"^#{1,6}\s+", md, re.MULTILINE))
    char_count = len(md)

    output_path.write_text(md, encoding="utf-8")
    print(f"OK ({word_count:,} words, {heading_count} sections, {char_count:,} chars)")

    return {
        "title": title,
        "filename": output_path.name,
        "word_count": word_count,
        "heading_count": heading_count,
        "char_count": char_count,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(count: int, delay: float):
    print(f"Wikipedia Test Document Fetcher")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Target: {count} article(s)\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Curated articles first, then top up with random ones to reach `count`.
    work: List[Tuple[str, str]] = list(ARTICLES)
    if count > len(work):
        print(f"  Fetching {count - len(work)} random article titles...")
        for t in fetch_random_titles(count - len(work)):
            work.append((t, _slug(t)))
    work = work[:count]

    stats = []
    errors = []

    for title, filename in work:
        output_path = OUTPUT_DIR / filename
        try:
            s = fetch_and_convert(title, output_path)
            stats.append(s)
        except urllib.error.HTTPError as e:
            print(f"FAILED ({e.code} {e.reason})")
            errors.append((title, str(e)))
        except Exception as e:
            print(f"FAILED ({e})")
            errors.append((title, str(e)))
        if delay:
            time.sleep(delay)

    # Write manifest
    if stats:
        manifest_path = OUTPUT_DIR / "manifest.json"
        manifest = {
            "description": "Wikipedia articles converted to markdown for segmentation testing",
            "articles": stats,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"\nManifest written to {manifest_path}")

    # Summary
    print(f"\n{'='*60}")
    print(f"Fetched {len(stats)}/{len(ARTICLES)} articles")
    if stats:
        total_words = sum(s["word_count"] for s in stats)
        total_headings = sum(s["heading_count"] for s in stats)
        print(f"Total: {total_words:,} words, {total_headings} sections")
    if errors:
        print(f"\nErrors:")
        for title, err in errors:
            print(f"  - {title}: {err}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch Wikipedia articles as markdown for document/segmentation testing")
    parser.add_argument("--count", type=int, default=len(ARTICLES),
                        help=f"Number of articles to fetch (default: {len(ARTICLES)} curated; "
                             f"more are filled with random articles)")
    parser.add_argument("--delay", type=float, default=0.3,
                        help="Seconds to sleep between fetches (be polite to Wikipedia)")
    args = parser.parse_args()
    main(args.count, args.delay)
