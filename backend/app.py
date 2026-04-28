"""
MOF Discovery API
FastAPI backend with SSE streaming for live extraction status.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import UPLOADS_DIR
from extraction.search import search_all
from extraction.fulltext import resolve_fulltext, assess_fulltext_quality
from extraction.parse import pmc_xml_to_text, pdf_to_text
from extraction.extract import extract_with_llm
from extraction.models import PaperMeta
from database.mof_db import (
    upsert_paper, update_paper_status, paper_already_done,
    insert_literature_mofs, import_core_mof_csv,
    import_core_mof_directory as import_core_mof_directory_files,
    query_mofs, get_mof_measurements, get_mofs_by_paper, list_papers, get_db_stats, get_paper,
)
from database.vector_store import index_paper
from agent.qa import dispatch

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="MOF Discovery API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory job store for SSE streaming ────────────────────────────────────
_jobs: dict[str, asyncio.Queue] = {}


# ── Models ────────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    limit: int = 5
    year: Optional[int] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    sort_by: str = "relevance"
    sources: list[str] = ["semantic_scholar", "pubmed", "openalex"]


class ExtractRequest(BaseModel):
    papers: list[dict]   # list of paper dicts from search
    skip_already_done: bool = True


class AssessRequest(BaseModel):
    papers: list[dict]


class AskRequest(BaseModel):
    query: str
    mode: str = "auto"   # "auto" | "question" | "hypothesis" | "chitchat"
    history: list[dict] = []  # [{role: "user"|"assistant", content: "..."}]
    deepread_n: int = 3  # max number of web papers to fetch full text + extract MOFs from


# ── Search ────────────────────────────────────────────────────────────────────

@app.post("/api/papers/search")
async def search_papers(req: SearchRequest):
    if req.limit > 20:
        raise HTTPException(400, "Search limit must be 20 or fewer.")
    results = await asyncio.get_event_loop().run_in_executor(
        None, lambda: search_all(
            query=req.query, limit=req.limit, year=req.year,
            date_from=req.date_from, date_to=req.date_to,
            sort_by=req.sort_by, sources=req.sources,
        )
    )
    return {"papers": results, "count": len(results)}


@app.post("/api/papers/assess")
async def assess_papers(req: AssessRequest):
    if len(req.papers) > 20:
        raise HTTPException(400, "Maximum 20 papers per full-text check.")

    loop = asyncio.get_event_loop()
    assessments = []
    for paper in req.papers:
        pid = await loop.run_in_executor(None, lambda p=paper: upsert_paper(p))
        text, msg, method = await loop.run_in_executor(None, lambda p=paper: resolve_fulltext(p))
        if method == "pmc_xml" and text:
            try:
                text = await loop.run_in_executor(None, lambda t=text: pmc_xml_to_text(t))
            except Exception as e:
                quality = {
                    "can_extract": False, "quality": "parse_error", "chars": 0,
                    "reason": f"PMC XML parse error: {e}", "method": method,
                }
                assessments.append({"paper_db_id": pid, "paperId": paper.get("paperId"),
                                    "title": paper.get("title", ""), "message": msg, **quality})
                continue
        quality = assess_fulltext_quality(text, method)
        await loop.run_in_executor(
            None,
            lambda pid=pid, q=quality: update_paper_status(
                pid,
                "pending" if q["can_extract"] else "failed",
                "" if q["can_extract"] else q["reason"],
                fulltext_chars=q["chars"],
                fulltext_method=q["method"],
            ),
        )
        assessments.append({"paper_db_id": pid, "paperId": paper.get("paperId"),
                            "title": paper.get("title", ""), "message": msg, **quality})
    return {"assessments": assessments}


# ── Extraction ────────────────────────────────────────────────────────────────

@app.post("/api/papers/extract")
async def start_extraction(req: ExtractRequest, background_tasks: BackgroundTasks):
    if len(req.papers) > 20:
        raise HTTPException(400, "Maximum 20 papers per extraction run.")
    job_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _jobs[job_id] = queue
    background_tasks.add_task(_run_extraction, job_id, queue, req.papers, req.skip_already_done)
    return {"job_id": job_id}


@app.get("/api/papers/extract/stream/{job_id}")
async def stream_extraction(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(404, "Job not found")

    async def event_stream():
        queue = _jobs[job_id]
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=120.0)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("type") == "done":
                    break
            except asyncio.TimeoutError:
                yield "data: {\"type\": \"ping\"}\n\n"
        _jobs.pop(job_id, None)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _run_extraction(job_id: str, queue: asyncio.Queue, papers: list[dict], skip_done: bool):
    loop = asyncio.get_event_loop()

    async def emit(msg: dict):
        await queue.put(msg)

    for paper in papers:
        paper_id_key = paper.get("doi") or paper.get("title", "")[:60]
        title = (paper.get("title") or "Untitled")[:80]

        # Check if already processed
        if skip_done:
            done, status = await loop.run_in_executor(
                None, lambda: paper_already_done(paper.get("doi", ""), paper.get("title", ""))
            )
            if done:
                await emit({"type": "skip", "paper": paper_id_key, "title": title, "status": status})
                continue

        await emit({"type": "fetching", "paper": paper_id_key, "title": title})

        # Upsert paper row
        pid = await loop.run_in_executor(None, lambda: upsert_paper(paper))
        await loop.run_in_executor(None, lambda: update_paper_status(pid, "fetching"))

        # Full-text fetch
        text, msg, method = await loop.run_in_executor(None, lambda: resolve_fulltext(paper))

        if not text or len(text) < 2000:
            reason = msg if not text else f"only {len(text)} chars ({method})"
            await loop.run_in_executor(
                None, lambda: update_paper_status(pid, "failed", reason))
            await emit({"type": "failed", "paper": paper_id_key, "title": title,
                        "reason": reason, "paper_db_id": pid,
                        "can_upload": True})
            continue

        # PMC XML → plain text
        if method == "pmc_xml":
            try:
                text = await loop.run_in_executor(None, lambda: pmc_xml_to_text(text))
            except Exception as e:
                reason = f"PMC XML parse error: {e}"
                await loop.run_in_executor(
                    None, lambda: update_paper_status(pid, "failed", reason))
                await emit({"type": "failed", "paper": paper_id_key, "title": title,
                            "reason": reason, "paper_db_id": pid, "can_upload": True})
                continue

        quality = assess_fulltext_quality(text, method)
        if not quality["can_extract"]:
            reason = quality["reason"]
            await loop.run_in_executor(
                None, lambda: update_paper_status(pid, "failed", reason,
                                                  fulltext_chars=quality["chars"],
                                                  fulltext_method=method))
            await emit({"type": "failed", "paper": paper_id_key, "title": title,
                        "reason": reason, "paper_db_id": pid, "can_upload": True,
                        "chars": quality["chars"], "method": method})
            continue

        char_count = len(text)
        await loop.run_in_executor(
            None, lambda: update_paper_status(pid, "extracting",
                                              fulltext_chars=char_count, fulltext_method=method))
        await emit({"type": "extracting", "paper": paper_id_key, "title": title,
                    "chars": char_count, "method": method})

        # LLM extraction
        meta = PaperMeta(
            title=paper.get("title", ""), year=paper.get("year"),
            url=paper.get("url", ""), doi=paper.get("doi", ""),
            source=paper.get("source", "semantic_scholar"), pmcid=paper.get("pmcid", ""),
            open_access_pdf=paper.get("open_access_pdf", ""),
            citation_count=paper.get("citationCount") or paper.get("citation_count"),
            publication_date=paper.get("publicationDate") or paper.get("publication_date", ""),
            abstract=paper.get("abstract", ""),
            authors=paper.get("authors", []),
        )
        result = await loop.run_in_executor(None, lambda: extract_with_llm(text, meta))

        if result.mofs:
            n_measurements = await loop.run_in_executor(
                None, lambda: insert_literature_mofs(
                    pid, paper.get("doi", ""), paper.get("title", ""), result.mofs))
            await loop.run_in_executor(
                None, lambda: update_paper_status(pid, "extracted"))
            await loop.run_in_executor(
                None, lambda: index_paper(pid, paper.get("title", ""),
                                          paper.get("doi", ""), text))
            await emit({"type": "extracted", "paper": paper_id_key, "title": title,
                        "mof_count": len(result.mofs),
                        "measurement_count": n_measurements,
                        "mof_names": [m.mof_name for m in result.mofs],
                        "paper_db_id": pid})
        else:
            await loop.run_in_executor(
                None, lambda: update_paper_status(pid, "no_mofs"))
            await loop.run_in_executor(
                None, lambda: index_paper(pid, paper.get("title", ""),
                                          paper.get("doi", ""), text))
            await emit({"type": "no_mofs", "paper": paper_id_key, "title": title,
                        "paper_db_id": pid, "can_upload": True})

    await emit({"type": "done"})


# ── PDF Upload (for failed papers) ────────────────────────────────────────────

@app.post("/api/papers/{paper_db_id}/upload")
async def upload_pdf(paper_db_id: int, background_tasks: BackgroundTasks,
                     file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files accepted")

    save_path = UPLOADS_DIR / f"paper_{paper_db_id}_{uuid.uuid4().hex[:8]}.pdf"
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    job_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _jobs[job_id] = queue
    background_tasks.add_task(_extract_uploaded_pdf, job_id, queue, paper_db_id, save_path)
    return {"job_id": job_id, "message": "PDF received, extracting..."}


async def _extract_uploaded_pdf(job_id: str, queue: asyncio.Queue,
                                 paper_db_id: int, pdf_path: Path):
    loop = asyncio.get_event_loop()
    try:
        paper = get_paper(paper_db_id)
        if not paper:
            await queue.put({"type": "error", "reason": "Paper not found in DB"})
            await queue.put({"type": "done"})
            return

        await queue.put({"type": "extracting", "paper": paper_db_id,
                         "title": paper.get("title", ""), "method": "pdf_upload"})
        await loop.run_in_executor(
            None, lambda: update_paper_status(paper_db_id, "extracting",
                                              fulltext_method="pdf_upload"))

        text = await loop.run_in_executor(None, lambda: pdf_to_text(str(pdf_path)))
        quality = assess_fulltext_quality(text, "pdf_upload")
        if not quality["can_extract"]:
            await loop.run_in_executor(
                None, lambda: update_paper_status(paper_db_id, "failed", quality["reason"],
                                                  fulltext_chars=quality["chars"],
                                                  fulltext_method="pdf_upload"))
            await queue.put({"type": "failed", "reason": quality["reason"],
                             "chars": quality["chars"], "method": "pdf_upload"})
            await queue.put({"type": "done"})
            return

        meta = PaperMeta(title=paper.get("title", ""), doi=paper.get("doi", ""),
                         source=paper.get("source", "upload"))
        result = await loop.run_in_executor(None, lambda: extract_with_llm(text, meta))

        if result.mofs:
            n_measurements = await loop.run_in_executor(
                None, lambda: insert_literature_mofs(
                    paper_db_id, paper.get("doi", ""), paper.get("title", ""), result.mofs))
            await loop.run_in_executor(
                None, lambda: update_paper_status(paper_db_id, "extracted",
                                                  fulltext_chars=len(text), fulltext_method="pdf_upload"))
            await loop.run_in_executor(
                None, lambda: index_paper(paper_db_id, paper.get("title", ""),
                                          paper.get("doi", ""), text))
            await queue.put({"type": "extracted",
                             "mof_count": len(result.mofs),
                             "measurement_count": n_measurements,
                             "mof_names": [m.mof_name for m in result.mofs]})
        else:
            await loop.run_in_executor(
                None, lambda: update_paper_status(paper_db_id, "no_mofs"))
            await loop.run_in_executor(
                None, lambda: index_paper(paper_db_id, paper.get("title", ""),
                                          paper.get("doi", ""), text))
            await queue.put({"type": "no_mofs"})
    except Exception as e:
        await queue.put({"type": "error", "reason": str(e)})
    finally:
        pdf_path.unlink(missing_ok=True)
        await queue.put({"type": "done"})


# ── Papers list ───────────────────────────────────────────────────────────────

@app.get("/api/papers")
async def get_papers(limit: int = Query(200, le=500)):
    papers = await asyncio.get_event_loop().run_in_executor(None, lambda: list_papers(limit))
    return {"papers": papers}


# ── MOF Database ──────────────────────────────────────────────────────────────

@app.get("/api/mofs")
async def get_mofs(
    source: Optional[str] = None,
    metal: Optional[str] = None,
    application_type: Optional[str] = None,
    min_surface_area: Optional[float] = None,
    min_co2_uptake: Optional[float] = None,
    min_selectivity: Optional[float] = None,
    search: Optional[str] = None,
    sort_by: str = "surface_area_m2_g",
    sort_desc: bool = True,
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    loop = asyncio.get_event_loop()
    mofs, total = await loop.run_in_executor(None, lambda: query_mofs(
        source=source, metal=metal, application_type=application_type,
        min_surface_area=min_surface_area, min_co2_uptake=min_co2_uptake,
        min_selectivity=min_selectivity, search=search,
        sort_by=sort_by, sort_desc=sort_desc, limit=limit, offset=offset,
    ))
    return {"mofs": mofs, "total": total, "limit": limit, "offset": offset}


@app.get("/api/mofs/stats")
async def db_stats():
    stats = await asyncio.get_event_loop().run_in_executor(None, get_db_stats)
    return stats


@app.get("/api/mofs/{mof_id}/measurements")
async def get_measurements(mof_id: int):
    rows = await asyncio.get_event_loop().run_in_executor(
        None, lambda: get_mof_measurements(mof_id)
    )
    return {"measurements": rows}


@app.get("/api/papers/{paper_id}/mofs")
async def get_paper_mofs(paper_id: int):
    rows = await asyncio.get_event_loop().run_in_executor(
        None, lambda: get_mofs_by_paper(paper_id)
    )
    return {"mofs": rows}


@app.post("/api/mofs/import-core")
async def import_core(csv_path: str):
    """Import CoRE MOF CSV. csv_path should be absolute path on server."""
    if not os.path.exists(csv_path):
        raise HTTPException(404, f"File not found: {csv_path}")
    loop = asyncio.get_event_loop()
    count = await loop.run_in_executor(None, lambda: import_core_mof_csv(csv_path))
    return {"imported": count}


@app.post("/api/mofs/import-core-directory")
async def import_core_directory(directory_path: str):
    """Import Becc's CoRE MOF ASR/FSR directory."""
    if not os.path.isdir(directory_path):
        raise HTTPException(404, f"Directory not found: {directory_path}")
    loop = asyncio.get_event_loop()
    imported = await loop.run_in_executor(None, lambda: import_core_mof_directory_files(directory_path))
    return {"imported": imported, "total": sum(imported.values())}


# ── Ask / Hypothesis ──────────────────────────────────────────────────────────

@app.post("/api/ask")
async def ask(req: AskRequest):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: dispatch(req.query, req.history, req.mode, deepread_n=req.deepread_n)
    )
    return result


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    from config import OPENAI_API_KEY, GROQ_KEY, SEMANTIC_SCHOLAR_KEY
    return {
        "status": "ok",
        "llm": "openai" if OPENAI_API_KEY else "groq" if GROQ_KEY else "none",
        "search": bool(SEMANTIC_SCHOLAR_KEY),
    }
