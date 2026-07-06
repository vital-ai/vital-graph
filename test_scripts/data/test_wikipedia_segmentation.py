#!/usr/bin/env python3
"""
Sanity-check that fetched Wikipedia markdown files segment correctly
with the markdown heading segmenter.

Reads all .md files from test_files/wikipedia/, runs the
DocumentSegmenter with MarkdownSegmentConfig, and prints per-file
and aggregate statistics.

Usage:
    python test_scripts/data/test_wikipedia_segmentation.py
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.document.document_segmenter import DocumentSegmenter, detect_is_markdown
from vitalgraph.document.segment_config import MarkdownSegmentConfig

WIKI_DIR = project_root / "test_files" / "wikipedia"

# Use local-model-friendly settings for testing (MiniLM max input = 128 tokens).
# Production default is 1024 tokens targeting OpenAI text-embedding-3-small.
LOCAL_MODEL_CONFIG = MarkdownSegmentConfig(max_segment_tokens=128, min_segment_tokens=20)
OPENAI_CONFIG = MarkdownSegmentConfig()  # uses production default (1024 tokens)


def main():
    md_files = sorted(WIKI_DIR.glob("*.md"))
    if not md_files:
        print(f"No .md files found in {WIKI_DIR}")
        print("Run fetch_wikipedia_test_docs.py first.")
        sys.exit(1)

    segmenter = DocumentSegmenter()
    all_ok = True

    configs = [
        ("Local (128 tok)", LOCAL_MODEL_CONFIG),
        ("OpenAI (1024 tok)", OPENAI_CONFIG),
    ]

    for config_label, config in configs:
        total_segments = 0
        total_words = 0

        print(f"\n=== {config_label} ===")
        print(f"{'File':<45s}  {'MD?':>3s}  {'Segs':>5s}  {'AvgTok':>6s}  {'MinTok':>6s}  {'MaxTok':>6s}  {'Words':>7s}")
        print("-" * 95)

        for md_file in md_files:
            text = md_file.read_text(encoding="utf-8")
            is_md = detect_is_markdown(text)
            segments = segmenter.segment(text, config)
            word_count = len(text.split())

            if segments:
                avg_tok = sum(s.token_length for s in segments) // len(segments)
                min_tok = min(s.token_length for s in segments)
                max_tok = max(s.token_length for s in segments)
            else:
                avg_tok = min_tok = max_tok = 0

            ok = is_md and len(segments) >= 3
            status = "" if ok else " ⚠"
            if not ok:
                all_ok = False

            print(
                f"{md_file.name:<45s}  {str(is_md):>3s}  {len(segments):>5d}  "
                f"{avg_tok:>6d}  {min_tok:>6d}  {max_tok:>6d}  {word_count:>7,d}{status}"
            )

            total_segments += len(segments)
            total_words += word_count

        print("-" * 95)
        print(f"{'TOTAL':<45s}  {'':>3s}  {total_segments:>5d}  {'':>6s}  {'':>6s}  {'':>6s}  {total_words:>7,d}")

    print()
    if all_ok:
        print("All files detected as markdown and produced >= 3 segments.")
    else:
        print("Some files had issues (marked with ⚠).")
        sys.exit(1)


if __name__ == "__main__":
    main()
