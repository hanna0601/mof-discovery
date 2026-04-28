"""
Multi-source paper search: Semantic Scholar, PubMed, OpenAlex.
Returns a normalised list of PaperMeta-compatible dicts.
"""
from __future__ import annotations
import re
import time
import requests
from typing import Optional
from config import SEMANTIC_SCHOLAR_KEY, NCBI_API_KEY, USER_AGENT

_SS_BASE  = "https://api.semanticscholar.org/graph/v1/paper/search"
_SS_HEADS = {"User-Agent": USER_AGENT,
             **({"x-api-key": SEMANTIC_SCHOLAR_KEY} if SEMANTIC_SCHOLAR_KEY else {})}

_ALEX_BASE = "https://api.openalex.org/works"
_PUBMED_SEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_PUBMED_FETCH  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_PUBMED_SUM    = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


# ── Semantic Scholar ──────────────────────────────────────────────────────────

def search_semantic_scholar(
    query: str,
    limit: int = 5,
    year: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort_by: str = "relevance",  # relevance | citations | newest
) -> list[dict]:
    fields = ("title,abstract,year,publicationDate,citationCount,"
              "openAccessPdf,isOpenAccess,externalIds,paperId,authors")
    params: dict = {"query": query, "fields": fields, "limit": limit}
    if year:
        params["year"] = str(year)
    elif date_from or date_to:
        start = (date_from or "1900-01-01")[:4]
        end = (date_to or "2099-12-31")[:4]
        params["year"] = f"{start}-{end}"
    if sort_by == "citations":
        params["sort"] = "citationCount:desc"
    elif sort_by == "newest":
        params["sort"] = "publicationDate:desc"

    try:
        r = requests.get(_SS_BASE, headers=_SS_HEADS, params=params, timeout=20)
        if r.status_code == 429:
            time.sleep(10)
            r = requests.get(_SS_BASE, headers=_SS_HEADS, params=params, timeout=20)
        r.raise_for_status()
        papers = r.json().get("data", []) or []
    except Exception:
        return []

    out = []
    for p in papers:
        ext = p.get("externalIds") or {}
        pdf = (p.get("openAccessPdf") or {}).get("url") if isinstance(p.get("openAccessPdf"), dict) else None
        out.append({
            "title":           p.get("title") or "",
            "abstract":        p.get("abstract") or "",
            "year":            p.get("year"),
            "citationCount":   p.get("citationCount") or 0,
            "pmcid":           ext.get("PubMedCentral") or "",
            "open_access_pdf": pdf or "",
            "doi":             ext.get("DOI") or "",
            "pmid":            ext.get("PubMed") or "",
            "paperId":         p.get("paperId") or "",
            "url":             f"https://www.semanticscholar.org/paper/{p['paperId']}" if p.get("paperId") else "",
            "source":          "semantic_scholar",
            "publicationDate": p.get("publicationDate") or "",
            "authors":         [a.get("name", "") for a in (p.get("authors") or [])],
        })
    return out


# ── PubMed ────────────────────────────────────────────────────────────────────

def search_pubmed(query: str, limit: int = 5, year: Optional[int] = None,
                  date_from: Optional[str] = None, date_to: Optional[str] = None) -> list[dict]:
    key_param = f"&api_key={NCBI_API_KEY}" if NCBI_API_KEY else ""
    if year:
        date_param = f"&datetype=pdat&mindate={year}/01/01&maxdate={year}/12/31"
    elif date_from or date_to:
        start = (date_from or "1900-01-01").replace("-", "/")
        end = (date_to or "3000-12-31").replace("-", "/")
        date_param = f"&datetype=pdat&mindate={start}&maxdate={end}"
    else:
        date_param = ""

    try:
        r = requests.get(
            f"{_PUBMED_SEARCH}?db=pubmed&term={requests.utils.quote(query)}"
            f"&retmode=json&retmax={limit}{date_param}{key_param}",
            timeout=15,
        )
        r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])
    except Exception:
        return []

    if not ids:
        return []

    # Fetch summaries
    try:
        sr = requests.get(
            f"{_PUBMED_SUM}?db=pubmed&id={','.join(ids)}&retmode=json{key_param}",
            timeout=15,
        )
        sr.raise_for_status()
        summaries = sr.json().get("result", {})
    except Exception:
        return []

    # Fetch abstracts via XML
    abstracts: dict[str, str] = {}
    try:
        fr = requests.get(
            f"{_PUBMED_FETCH}?db=pubmed&id={','.join(ids)}&retmode=xml{key_param}",
            timeout=20,
        )
        fr.raise_for_status()
        xml = fr.text
        for pmid in ids:
            pat = re.compile(
                rf"<PMID[^>]*>{re.escape(pmid)}</PMID>([\s\S]*?)</PubmedArticle>", re.I)
            m = pat.search(xml)
            if m:
                abst = re.findall(r"<AbstractText[^>]*>([\s\S]*?)</AbstractText>", m.group(1), re.I)
                abstracts[pmid] = " ".join(re.sub(r"<[^>]+>", "", a) for a in abst)
    except Exception:
        pass

    out = []
    for pmid in ids:
        item = summaries.get(pmid, {})
        doi_list = [uid.get("value", "") for uid in (item.get("articleids") or [])
                    if uid.get("idtype") == "doi"]
        doi = doi_list[0] if doi_list else ""
        pmcid_list = [uid.get("value", "") for uid in (item.get("articleids") or [])
                      if uid.get("idtype") == "pmc"]
        pmcid = pmcid_list[0].replace("PMC", "") if pmcid_list else ""
        out.append({
            "title":           item.get("title", ""),
            "abstract":        abstracts.get(pmid, ""),
            "year":            int(item.get("pubdate", "0")[:4]) if item.get("pubdate") else None,
            "citationCount":   0,
            "pmcid":           pmcid,
            "open_access_pdf": "",
            "doi":             doi,
            "pmid":            pmid,
            "paperId":         f"pubmed-{pmid}",
            "url":             f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "source":          "pubmed",
            "publicationDate": item.get("pubdate", ""),
            "authors":         [a.get("name", "") for a in (item.get("authors") or [])],
        })
    return out


# ── OpenAlex ─────────────────────────────────────────────────────────────────

def search_openalex(query: str, limit: int = 5, year: Optional[int] = None,
                    date_from: Optional[str] = None, date_to: Optional[str] = None,
                    sort_by: str = "relevance") -> list[dict]:
    params: dict = {"search": query, "per-page": limit}
    if year:
        params["filter"] = f"publication_year:{year}"
    elif date_from or date_to:
        filters = []
        if date_from:
            filters.append(f"from_publication_date:{date_from}")
        if date_to:
            filters.append(f"to_publication_date:{date_to}")
        params["filter"] = ",".join(filters)
    if sort_by == "citations":
        params["sort"] = "cited_by_count:desc"
    elif sort_by == "newest":
        params["sort"] = "publication_date:desc"

    try:
        r = requests.get(_ALEX_BASE, params=params,
                         headers={"User-Agent": USER_AGENT}, timeout=15)
        r.raise_for_status()
        works = r.json().get("results", [])
    except Exception:
        return []

    out = []
    for w in works:
        abstract = ""
        if w.get("abstract_inverted_index"):
            idx = w["abstract_inverted_index"]
            words: list[str] = []
            for word, positions in idx.items():
                for pos in positions:
                    while len(words) <= pos:
                        words.append("")
                    words[pos] = word
            abstract = " ".join(words)

        doi = (w.get("doi") or "").replace("https://doi.org/", "")
        out.append({
            "title":           w.get("title") or "",
            "abstract":        abstract,
            "year":            w.get("publication_year"),
            "citationCount":   w.get("cited_by_count") or 0,
            "pmcid":           "",
            "open_access_pdf": (w.get("open_access") or {}).get("oa_url") or "",
            "doi":             doi,
            "pmid":            "",
            "paperId":         f"openalex-{w['id'].split('/')[-1]}",
            "url":             doi and f"https://doi.org/{doi}" or w.get("id", ""),
            "source":          "openalex",
            "publicationDate": w.get("publication_date") or "",
            "authors":         [a.get("author", {}).get("display_name", "")
                                for a in (w.get("authorships") or [])],
        })
    return out


# ── Combined ──────────────────────────────────────────────────────────────────

def search_all(
    query: str,
    limit: int = 5,
    year: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort_by: str = "relevance",
    sources: list[str] | None = None,
) -> list[dict]:
    """Search all enabled sources and return deduplicated results."""
    if sources is None:
        sources = ["semantic_scholar", "pubmed", "openalex"]

    results: list[dict] = []
    if "semantic_scholar" in sources:
        results += search_semantic_scholar(query, limit, year, date_from, date_to, sort_by)
    if "pubmed" in sources:
        results += search_pubmed(query, limit, year, date_from, date_to)
    if "openalex" in sources:
        results += search_openalex(query, limit, year, date_from, date_to, sort_by)

    # Deduplicate by DOI, then by title similarity
    seen_dois: set[str] = set()
    seen_titles: set[str] = set()
    deduped = []
    for p in results:
        doi = (p.get("doi") or "").strip().lower()
        title_key = re.sub(r"[^a-z0-9]", "", (p.get("title") or "").lower())[:60]
        if doi and doi in seen_dois:
            continue
        if title_key and title_key in seen_titles:
            continue
        if doi:
            seen_dois.add(doi)
        if title_key:
            seen_titles.add(title_key)
        deduped.append(p)

    if sort_by == "citations":
        deduped.sort(key=lambda p: p.get("citationCount") or 0, reverse=True)
    elif sort_by == "newest":
        deduped.sort(key=lambda p: p.get("publicationDate") or str(p.get("year") or ""), reverse=True)

    return deduped[:limit]
