"""
Unit tests for document → Markdown conversion (issue 018 item 4).

The property that matters throughout: conversion must produce ATX headings
(`# Foo`), because that is what the segmenter's detect_is_markdown looks for.
A conversion that loses headings is worse than useless — it silently downgrades
every document to the paragraph splitter.
"""

import io
import zipfile

import pytest

from vitalgraph.document.document_converter import (
    ConversionError,
    convert_to_markdown,
    html_to_markdown,
    is_supported,
    normalise_extension,
)
from vitalgraph.document.document_segmenter import detect_is_markdown


class TestExtensionHandling:
    def test_normalise_extension_lowercases(self):
        assert normalise_extension("Report.PDF") == ".pdf"

    def test_normalise_extension_without_dot(self):
        assert normalise_extension("README") == ""

    def test_supported_and_unsupported(self):
        assert is_supported("a.html")
        assert is_supported("a.docx")
        assert is_supported("a.pdf")
        assert is_supported("a.md")
        assert not is_supported("a.xlsx")

    def test_unsupported_raises_rather_than_storing_garbage(self):
        with pytest.raises(ConversionError, match="Unsupported file type"):
            convert_to_markdown(b"\x00\x01binary", "sheet.xlsx")


class TestHtml:
    HTML = """
    <html><body>
      <h1>Coffee</h1>
      <p>A <strong>brewed</strong> drink.</p>
      <h2>History</h2>
      <p>Origins in Ethiopia.</p>
      <ul><li>Arabica</li><li>Robusta</li></ul>
    </body></html>
    """

    def test_headings_survive_as_atx(self):
        md = html_to_markdown(self.HTML)
        assert "# Coffee" in md
        assert "## History" in md

    def test_segmenter_would_choose_heading_split(self):
        md = html_to_markdown(self.HTML)
        # The whole point of converting: two or more headings flips the
        # segmenter onto markdown_heading_split.
        assert detect_is_markdown(md) is True

    def test_inline_formatting_and_lists_preserved(self):
        md = html_to_markdown(self.HTML)
        assert "**brewed**" in md
        assert "Arabica" in md

    def test_original_html_is_returned_for_preservation(self):
        result = convert_to_markdown(self.HTML.encode(), "page.html")
        assert result.converted is True
        assert result.original_html is not None
        assert "<h1>" in result.original_html
        assert result.heading_count >= 2

    def test_non_utf8_does_not_lose_the_body(self):
        latin1 = "<h1>Caf\xe9</h1><h2>Cr\xe8me</h2>".encode("latin-1")
        result = convert_to_markdown(latin1, "page.html")
        assert "# Caf" in result.markdown


class TestPassthrough:
    def test_markdown_is_not_reconverted(self):
        src = b"# One\n\nBody.\n\n## Two\n\nMore.\n"
        result = convert_to_markdown(src, "notes.md")
        assert result.converted is False
        assert result.markdown.startswith("# One")
        assert result.heading_count == 2

    def test_plain_text_passes_through_without_inventing_structure(self):
        result = convert_to_markdown(b"Just a sentence.\nAnd another.", "notes.txt")
        assert result.converted is False
        assert "#" not in result.markdown
        assert detect_is_markdown(result.markdown) is False

    def test_excess_blank_lines_collapsed(self):
        result = convert_to_markdown(b"A\n\n\n\n\nB", "notes.txt")
        assert "\n\n\n" not in result.markdown


class TestDocx:
    @staticmethod
    def _docx_bytes() -> bytes:
        """
        Build a minimal but real .docx: a zip with the parts mammoth needs, using
        Word's built-in Heading 1/2 styles so the style→<h1> mapping is exercised.
        """
        document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Quarterly Report</w:t></w:r></w:p>
    <w:p><w:r><w:t>Revenue rose.</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Outlook</w:t></w:r></w:p>
    <w:p><w:r><w:t>Cautiously optimistic.</w:t></w:r></w:p>
  </w:body>
</w:document>"""
        content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
        rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", content_types)
            z.writestr("_rels/.rels", rels)
            z.writestr("word/document.xml", document_xml)
        return buf.getvalue()

    def test_word_heading_styles_become_markdown_headings(self):
        result = convert_to_markdown(self._docx_bytes(), "report.docx")
        assert result.converted is True
        assert "# Quarterly Report" in result.markdown
        assert "## Outlook" in result.markdown
        assert detect_is_markdown(result.markdown) is True

    def test_body_text_preserved(self):
        result = convert_to_markdown(self._docx_bytes(), "report.docx")
        assert "Revenue rose." in result.markdown

    def test_corrupt_docx_raises_rather_than_silently_empty(self):
        with pytest.raises(ConversionError, match="DOCX conversion failed"):
            convert_to_markdown(b"not a zip at all", "broken.docx")


class TestPdf:
    @staticmethod
    def _pdf_bytes(text: str = "Hello PDF") -> bytes:
        """A hand-built single-page PDF with a text layer, no library needed."""
        content = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
        out = bytearray(b"%PDF-1.4\n")
        offsets = []
        for i, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref_at = len(out)
        out += f"xref\n0 {len(objects) + 1}\n".encode()
        out += b"0000000000 65535 f \n"
        for off in offsets:
            out += f"{off:010d} 00000 n \n".encode()
        out += (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
        )
        return bytes(out)

    def test_text_extracted_with_page_headings(self):
        result = convert_to_markdown(self._pdf_bytes(), "doc.pdf")
        assert result.converted is True
        assert "## Page 1" in result.markdown
        assert "Hello PDF" in result.markdown

    def test_scanned_pdf_without_text_layer_is_reported(self):
        # A structurally valid PDF whose page draws no text — the scanned-image
        # case. It must be an explicit error, not an empty document that later
        # reads as a segmentation failure.
        with pytest.raises(ConversionError, match="no extractable text"):
            convert_to_markdown(self._pdf_bytes(text=""), "scan.pdf")

    def test_corrupt_pdf_raises(self):
        with pytest.raises(ConversionError, match="PDF conversion failed"):
            convert_to_markdown(b"%PDF-1.4 truncated garbage", "broken.pdf")
