from __future__ import annotations
import re
from typing import Optional


def pdf_to_text(pdf_path: str, max_pages: int = 80) -> str:
    import fitz
    doc = fitz.open(pdf_path)
    n = min(doc.page_count, max_pages)
    return _clean("\n".join(doc.load_page(i).get_text("text") for i in range(n)))


def pmc_xml_to_text(xml_text: str, max_chars: int = 150_000) -> str:
    from lxml import etree
    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(xml_text.encode("utf-8", errors="ignore"), parser=parser)

    parts = []
    title = root.xpath("string(//article-title)")
    if title:
        parts.append("TITLE: " + title.strip())

    abstract = " ".join(t.strip() for t in root.xpath("//abstract//text()") if t.strip())
    if abstract:
        parts.append("ABSTRACT: " + abstract)

    for sec in root.xpath("//body//sec"):
        heading = sec.xpath("string(./title)").strip()
        txt = " ".join(t.strip() for t in sec.xpath(".//text()") if t.strip())
        if txt:
            parts.append(f"SECTION: {heading}\n{txt}" if heading else txt)

    captions = [
        " ".join(t.strip() for t in cap.xpath(".//text()") if t.strip())
        for cap in root.xpath("//table-wrap//caption")
    ]
    if captions:
        parts.append("TABLE_CAPTIONS:\n" + "\n".join(c for c in captions if c))

    return _clean("\n\n".join(parts))[:max_chars]


def _clean(s: str) -> str:
    s = s.replace("\x00", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()
