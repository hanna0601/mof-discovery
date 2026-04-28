"""
Multi-strategy full-text resolver. Tries sources in priority order,
returns the first that yields ≥ 2000 chars of content.

Strategy order:
  1. Unpaywall  → repo/preprint PDF or landing page
  2. PMC XML    → NCBI eFetch (structured XML, best quality)
  3. EuropePMC  → separate corpus (chemistry journals)
  4. BS4        → plain requests + BeautifulSoup (fast, no JS)
  5. curl_cffi  → Chrome TLS fingerprint (bypasses Cloudflare)
  6. Publisher HTML → ACS/Wiley/Nature direct URLs
  7. Playwright → JS-heavy publishers (last resort, slow)
  8. PDF direct → download + PyMuPDF parse
"""
from __future__ import annotations
import os
import re
import tempfile
import requests
from typing import Optional, Tuple
from config import USER_AGENT, NCBI_API_KEY, UNPAYWALL_EMAIL
from .scrape import bs4_scrape, scrape_publisher_page, elsevier_doi_to_sciencedirect

PMC_EFETCH       = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPEPMC_FT     = "https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{id}/fullTextXML"
MIN_CHARS = 2000

_JS_PUBLISHERS = (
    "sciencedirect.com", "springer.com", "link.springer.com",
    "pubs.acs.org", "pubs.rsc.org", "onlinelibrary.wiley.com",
    "nature.com",
)


def resolve_fulltext(paper: dict) -> Tuple[Optional[str], str, str]:
    """
    Returns (text, message, method).
    method: pmc_xml | europepmc | unpaywall | bs4_doi | scrape_doi |
            publisher_html | playwright | pdf | failed
    """
    pmcid   = (paper.get("pmcid") or "").strip()
    pdf_url = (paper.get("open_access_pdf") or paper.get("pdf_url") or "").strip()
    doi     = (paper.get("doi") or "").strip()

    # Enrich missing DOI
    if not doi and not pmcid:
        ss_id = _ss_id_from_url(paper.get("url", ""))
        if ss_id:
            doi = _fetch_doi_ss(ss_id)

    # 1. Unpaywall
    if doi and not pmcid:
        oa_url = _unpaywall(doi)
        if oa_url:
            if oa_url.endswith(".pdf"):
                text = _dl_pdf(oa_url)
                if text and len(text) > MIN_CHARS:
                    return text, "unpaywall pdf", "unpaywall"
            else:
                text, _ = scrape_publisher_page(oa_url)
                if text and len(text) > MIN_CHARS:
                    return text, "unpaywall", "unpaywall"

    # 2. PMC XML
    if pmcid:
        xml, msg = _fetch_pmc_xml(pmcid)
        if xml:
            return xml, msg, "pmc_xml"

    # 2b. EuropePMC
    if doi and not pmcid:
        xml, msg = _europepmc(doi)
        if xml:
            return xml, msg, "europepmc"

    # 3. BS4 (fast)
    if doi:
        doi_url = f"https://doi.org/{doi}"

        # For RSC, doi.org redirects to articlelanding (abstract only) which
        # barely clears MIN_CHARS.  Go straight to articlehtml instead.
        if doi.lower().startswith("10.1039/"):
            rsc_url = _rsc_article_html_url(doi)
            if rsc_url:
                text, _ = bs4_scrape(rsc_url)
                if text and len(text) > MIN_CHARS:
                    return text, "rsc article html", "publisher_html"

        text, _ = bs4_scrape(doi_url)
        if text and len(text) > MIN_CHARS:
            return text, "bs4", "bs4_doi"

        # 4. curl_cffi
        sd_url = elsevier_doi_to_sciencedirect(doi)
        target = sd_url or doi_url
        text, _ = scrape_publisher_page(target)
        if text and len(text) > MIN_CHARS:
            return text, "scrape", "scrape_doi"

        # 5. Publisher HTML
        pub_url = _publisher_html_url(doi)
        if pub_url and pub_url != target:
            text, _ = bs4_scrape(pub_url)
            if text and len(text) > MIN_CHARS:
                return text, "publisher html", "publisher_html"

        # 6. Playwright
        if any(pub in target for pub in _JS_PUBLISHERS):
            text, msg = _playwright(target)
            if text:
                return text, msg, "playwright"

    # 7-8. PDF
    if pdf_url:
        landing = _pdf_landing(pdf_url)
        if landing:
            text, _ = scrape_publisher_page(landing)
            if text and len(text) > MIN_CHARS:
                return text, "pdf landing", "scrape_pdf_landing"

        text = _dl_pdf(pdf_url)
        if text and len(text) > MIN_CHARS:
            return text, "pdf download", "pdf"

    return None, "all strategies exhausted", "failed"


def assess_fulltext_quality(text: str | None, method: str = "") -> dict:
    """Estimate whether retrieved text is a full paper rather than abstract/first page only."""
    if not text:
        return {
            "can_extract": False,
            "quality": "missing",
            "chars": 0,
            "reason": "No full text was retrieved",
            "method": method,
        }

    lower = text.lower()
    chars = len(text)
    sections = sum(1 for marker in (
        "introduction", "experimental", "materials and methods", "results",
        "discussion", "conclusion", "references", "acknowledg"
    ) if marker in lower)
    has_tail = any(marker in lower[-30000:] for marker in ("references", "acknowledg", "supporting information"))
    only_beginning = chars < 12000 or (sections < 3 and not has_tail)

    if chars < MIN_CHARS:
        return {
            "can_extract": False,
            "quality": "too_short",
            "chars": chars,
            "reason": f"Only {chars} characters were retrieved",
            "method": method,
        }
    if only_beginning:
        return {
            "can_extract": False,
            "quality": "partial",
            "chars": chars,
            "reason": "Retrieved text looks partial; upload the PDF for a full-paper extraction",
            "method": method,
        }
    return {
        "can_extract": True,
        "quality": "full_text",
        "chars": chars,
        "reason": "Full-paper text found",
        "method": method,
    }


def _fetch_pmc_xml(pmcid: str) -> Tuple[Optional[str], str]:
    params = {"db": "pmc", "id": pmcid.replace("PMC", ""), "retmode": "xml"}
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    try:
        r = requests.get(PMC_EFETCH, params=params, timeout=45,
                         headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        return r.text, "ok"
    except Exception as e:
        return None, str(e)


def _europepmc(doi: str) -> Tuple[Optional[str], str]:
    try:
        r = requests.get(EUROPEPMC_SEARCH, params={
            "query": f'DOI:"{doi}"', "resultType": "lite", "format": "json", "pageSize": 1,
        }, headers={"User-Agent": USER_AGENT}, timeout=10)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        results = (r.json().get("resultList") or {}).get("result") or []
        if not results:
            return None, "not in EuropePMC"
        hit = results[0]
        if not (hit.get("isOpenAccess") == "Y" or hit.get("hasFullText") == "Y"):
            return None, "no open-access full text"
        ft_url = EUROPEPMC_FT.format(source=hit.get("source", ""), id=hit.get("id", ""))
        r2 = requests.get(ft_url, headers={"User-Agent": USER_AGENT}, timeout=30)
        if r2.status_code != 200 or len(r2.text) < 500:
            return None, "EuropePMC response too short"
        return r2.text, "ok"
    except Exception as e:
        return None, str(e)


def _unpaywall(doi: str) -> Optional[str]:
    if not UNPAYWALL_EMAIL:
        return None
    try:
        r = requests.get(f"https://api.unpaywall.org/v2/{doi}",
                         params={"email": UNPAYWALL_EMAIL}, timeout=10,
                         headers={"User-Agent": USER_AGENT})
        if r.status_code != 200:
            return None
        data = r.json()
        locs = data.get("oa_locations") or []
        for loc in locs:
            if loc.get("host_type") in ("repository", "preprint"):
                url = loc.get("url_for_pdf") or loc.get("url_for_landing_page")
                if url:
                    return url
        for loc in locs:
            url = loc.get("url_for_pdf") or loc.get("url_for_landing_page") or ""
            if url and "sciencedirect.com" not in url:
                return url
        best = data.get("best_oa_location") or {}
        return best.get("url_for_pdf") or best.get("url_for_landing_page")
    except Exception:
        return None


def _publisher_html_url(doi: str) -> Optional[str]:
    d = doi.lower()
    if d.startswith("10.1021/"):
        return f"https://pubs.acs.org/doi/full/{doi}"
    if d.startswith("10.1002/"):
        return f"https://onlinelibrary.wiley.com/doi/full/{doi}"
    if d.startswith("10.1038/"):
        return f"https://www.nature.com/articles/{doi.split('/', 1)[-1]}"
    if d.startswith("10.1039/"):
        return _rsc_article_html_url(doi)
    return None


def _rsc_article_html_url(doi: str) -> Optional[str]:
    """
    Follow the doi.org redirect for an RSC DOI to get the landing page URL,
    then swap 'articlelanding' → 'articlehtml' for the full-text HTML.
    Example: .../articlelanding/2011/ee/c1ee01720a → .../articlehtml/2011/ee/c1ee01720a
    """
    try:
        r = requests.head(
            f"https://doi.org/{doi}", timeout=10,
            headers={"User-Agent": USER_AGENT}, allow_redirects=True,
        )
        url = r.url
        if "pubs.rsc.org" in url:
            if "articlelanding" in url:
                return url.replace("articlelanding", "articlehtml")
            return url
    except Exception:
        pass
    return None


def _playwright(url: str) -> Tuple[Optional[str], str]:
    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup
    except ImportError:
        return None, "playwright not installed"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True,
                                        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            ctx.add_init_script('Object.defineProperty(navigator,"webdriver",{get:()=>undefined})')
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if "sciencedirect.com" in url:
                try:
                    page.wait_for_selector("#abstracts,.ArticleFull-articleBody,.Body", timeout=15000)
                except Exception:
                    page.wait_for_timeout(8000)
            else:
                page.wait_for_timeout(3000)
            html = page.content()
            browser.close()

        from .scrape import _parse_html
        text, msg = _parse_html(html, 1500)
        return text, msg or "playwright ok"
    except Exception as e:
        return None, str(e)


def _dl_pdf(url: str) -> Optional[str]:
    try:
        r = requests.get(url, timeout=45, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        if "pdf" not in (r.headers.get("Content-Type") or "").lower() and not r.content.startswith(b"%PDF"):
            return None
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(r.content)
            tmp = f.name
        from .parse import pdf_to_text
        text = pdf_to_text(tmp)
        os.unlink(tmp)
        return text
    except Exception:
        return None


def _pdf_landing(pdf_url: str) -> Optional[str]:
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(pdf_url)
    path = parsed.path
    for suffix in ("/pdf", "/full/pdf", "/epdf"):
        if path.endswith(suffix):
            return urlunparse(parsed._replace(path=path[:-len(suffix)], query="", fragment=""))
    if "/pdf" in path:
        return urlunparse(parsed._replace(path=path[:path.rfind("/pdf")], query="", fragment=""))
    return None


def _ss_id_from_url(url: str) -> Optional[str]:
    m = re.search(r"/paper/([a-f0-9]{40})", url)
    return m.group(1) if m else None


def _fetch_doi_ss(paper_id: str) -> str:
    try:
        from config import SEMANTIC_SCHOLAR_KEY
        headers = {"x-api-key": SEMANTIC_SCHOLAR_KEY} if SEMANTIC_SCHOLAR_KEY else {}
        r = requests.get(
            f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}",
            params={"fields": "externalIds"},
            headers={**headers, "User-Agent": USER_AGENT},
            timeout=10,
        )
        if r.status_code == 200:
            return (r.json().get("externalIds") or {}).get("DOI") or ""
    except Exception:
        pass
    return ""
