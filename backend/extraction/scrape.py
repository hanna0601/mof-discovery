from __future__ import annotations
from typing import Optional, Tuple
from config import USER_AGENT

_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def bs4_scrape(url: str, min_chars: int = 1500) -> Tuple[Optional[str], str]:
    try:
        import requests
        from bs4 import BeautifulSoup
        r = requests.get(url, headers={"User-Agent": _BROWSER_UA,
                                       "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                                       "Accept-Language": "en-US,en;q=0.9"},
                         timeout=20, allow_redirects=True)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return _parse_html(r.text, min_chars)
    except Exception as e:
        return None, str(e)


def scrape_publisher_page(url: str, min_chars: int = 1500) -> Tuple[Optional[str], str]:
    try:
        from curl_cffi import requests as cffi
        from bs4 import BeautifulSoup
        r = cffi.get(url, impersonate="chrome124", timeout=30)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return _parse_html(r.text, min_chars)
    except ImportError:
        return bs4_scrape(url, min_chars)
    except Exception as e:
        return None, str(e)


def elsevier_doi_to_sciencedirect(doi: str) -> Optional[str]:
    try:
        import re
        from curl_cffi import requests as cffi
        r = cffi.get(f"https://doi.org/{doi}", impersonate="chrome124", timeout=15, allow_redirects=True)
        for pattern in [r"/pii/(S\w+)", r"/pii/(S\w+)"]:
            m = re.search(pattern, r.url) or re.search(pattern, r.text)
            if m:
                return f"https://www.sciencedirect.com/science/article/abs/pii/{m.group(1)}"
    except Exception:
        pass
    return None


def _parse_html(html: str, min_chars: int) -> Tuple[Optional[str], str]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                     "figure", "figcaption", "noscript"]):
        tag.decompose()

    parts = []
    title = soup.find("h1") or soup.select_one(".article-title, .citation__title")
    if title:
        parts.append("TITLE: " + title.get_text(" ", strip=True))

    for sel in ["#Abs1-content", ".article_abstract-content", "#abstractBox",
                "#abstracts", ".abstract-content", "[class*='abstract']",
                ".Abstract", ".abstractSection",
                "#divAbstract"]:                # RSC
        el = soup.select_one(sel)
        if el:
            parts.append("ABSTRACT: " + el.get_text(" ", strip=True))
            break

    body_found = False
    for sel in [".NLM_sec", ".article-section__content", ".c-article-section",
                ".hlFld-Fulltext", ".fulltext-section", ".sect",
                "#divBody",                     # RSC full article body
                ".article__body",               # RSC alternative
                "article", "main", "section"]:
        sections = soup.select(sel)
        if sections:
            for s in sections:
                txt = s.get_text(" ", strip=True)
                if len(txt) > 100:
                    parts.append(txt)
                    body_found = True
            if body_found:
                break

    # Fall back to all <p> tags when no recognised section container was found
    # (e.g. RSC articlehtml, which uses bare <p> elements without a wrapper div)
    if not body_found:
        paras = [p.get_text(" ", strip=True)
                 for p in soup.find_all("p") if len(p.get_text()) > 80]
        parts.extend(paras)

    text = "\n\n".join(parts)
    if len(text) < min_chars:
        return None, f"Too little content ({len(text)} chars) — likely paywalled"
    return text[:120_000], "ok"
