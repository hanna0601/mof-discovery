"""
3-pipeline agent (Trisha's architecture adapted for mof-discovery):
  1. Intent routing  → hypothesis | question | chitchat
  2. Hypothesis      → Stage 2 Reasoning Agent + Stage 3 Critic Agent
  3. Question        → cited answer with conversation memory
  4. Chitchat        → MOF-aware direct response

Data sources: ChromaDB RAG (extracted papers) + SQLite (CoRE MOF + literature rows)
"""
from __future__ import annotations
import json
import logging
import re
import time
import requests
from config import OPENAI_API_KEY, OPENAI_MODEL, GROQ_KEY, GROQ_MODEL
from database.vector_store import retrieve, embed_texts, chunk_text
from database.mof_db import query_mofs, save_agent_memory, search_agent_memory
from extraction.fulltext import resolve_fulltext
from extraction.parse import pmc_xml_to_text
from extraction.search import search_all

logger = logging.getLogger(__name__)

# ── System prompts ─────────────────────────────────────────────────────────────

_INTENT_SYSTEM = """Classify the user message into exactly one word.
Reply with only: hypothesis, question, or chitchat.
- hypothesis: a testable claim about MOF properties or behaviour (e.g. "MOFs with open metal sites capture more CO2", "higher surface area means better CO2 uptake")
- question: a factual or research question (e.g. "What is the CO2 uptake of HKUST-1?", "Which MOFs are best for DAC?")
- chitchat: greetings, thanks, or anything not about MOF science"""

_REASONING_SYSTEM = """You are an expert MOF (Metal-Organic Framework) scientist evaluating a scientific hypothesis about CO2 capture.

Context is provided in five sections:
- SOURCE A: full-text excerpts from papers we have already extracted and indexed locally
- SOURCE B: MOF records from our database (CoRE MOF simulation data + literature-extracted values)
- SOURCE C: abstracts from a live web search of recent papers
- SOURCE D: full text of additional papers fetched live during this query (treat like SOURCE A — highest quality)
- SOURCE E: condensed findings from previous related queries answered by this system (use as background context, not primary evidence)

== EVALUATION PROTOCOL — follow these steps in order ==

STEP 1 — Classify and decompose the hypothesis.

  A) MATERIAL-SPECIFIC hypothesis (names a specific MOF or family, e.g. "MOF-5 degrades in humidity"):
     Identify: (a) specific material(s), (b) specific condition/context, (c) claimed mechanism/property.

  B) GENERAL / METHODOLOGICAL hypothesis (no specific material named, or makes a claim about a method,
     trend, or broad relationship, e.g. "IAST selectivity predicts real performance ranking"):
     Identify: (a) the method or metric being evaluated, (b) the claimed relationship or reliability,
     (c) the application context (e.g. "post-combustion", "DAC").

STEP 2 — Classify each piece of evidence:

  For TYPE A (material-specific) hypotheses:
  - DIRECT: addresses the SAME material + SAME condition + SAME mechanism → strong weight
  - INDIRECT: different but analogous material or condition → moderate weight
  - TANGENTIAL: shares keywords but tests a different mechanism or material → low weight
  - Do NOT conflate pyrolysis/heat decomposition with water/humidity degradation
  - Do NOT treat generic stability data as evidence for a specific bond-breaking mechanism

  For TYPE B (general/methodological) hypotheses:
  - DIRECT: paper explicitly tests or validates the method/metric against ground-truth measurements
    (e.g. comparing IAST predictions to breakthrough experiment results for the same material and conditions)
  - INDIRECT: paper applies the method and separately reports experimental data, without explicit
    comparison as a validation; or validates the method under different conditions
  - TANGENTIAL: paper only mentions the method in passing without using it as a predictive tool

STEP 3 — Verdict and confidence:

  For TYPE A hypotheses:
  - Confidence = 0.9: direct experimental evidence (XRD, IR, NMR, TGA) on the exact material and mechanism
  - Confidence = 0.7: direct evidence on an analogous system with a clear mechanistic parallel
  - Confidence = 0.5: indirect or mixed evidence
  - Confidence ≤ 0.3: only tangential or circumstantial evidence
  - Verdict must be "insufficient_data" if only tangential evidence exists

  For TYPE B hypotheses:
  - Confidence = 0.85: multiple independent papers directly validate the method across ≥3 MOF families
    or conditions, with quantitative agreement between predictions and experiments
  - Confidence = 0.65: ≥2 papers show direct validation (method predictions match experimental outcomes)
    for specific materials; the general claim is plausibly extrapolated but not exhaustively tested
  - Confidence = 0.5: 1 direct validation paper or consistent indirect evidence across several studies
  - Confidence ≤ 0.35: only indirect or tangential evidence; method is used but never explicitly validated
  - Verdict may be "partially_supported" (not "insufficient_data") when direct validation exists for
    specific cases but generalizability to all conditions is unproven

Only cite evidence that actually appears in the provided context:
- If from SOURCE A, C, or D, cite as [DOI] or [Author et al., Year]
- If from SOURCE B CoRE MOF, cite as [CoRE MOF: <name>]
- If from SOURCE B literature, cite as [DB literature: <name>]

Return JSON only — no prose before or after:
{
  "status": "supported" | "partially_supported" | "not_supported" | "insufficient_data",
  "summary": "One concise evaluation paragraph noting evidence quality (direct/indirect/tangential)",
  "reasons_for": ["supporting point — label evidence type and cite source", ...],
  "reasons_against": ["counter-point — label evidence type and cite source", ...],
  "data_gaps": ["specific missing evidence that would directly address the claimed mechanism", ...],
  "confidence": 0.0
}"""

_CRITIC_SYSTEM = """You are a rigorous scientific critic reviewing a MOF hypothesis evaluation.
Your job: challenge the reasoning agent's verdict — find weaknesses, missing counter-evidence, overlooked data, or overgeneralisation.

Pay special attention to:
- Evidence mismatch: is the cited evidence actually about the specific material and mechanism in the hypothesis, or is it tangential?
- Mechanism conflation: does the reasoning confuse different degradation/adsorption mechanisms?
- Analogy overreach: does it over-generalise from one MOF family to another without justification?

Return JSON only:
{
  "challenges": ["specific challenge with evidence or reasoning", ...],
  "overlooked_evidence": ["data or context the reasoning agent did not address", ...],
  "revised_confidence": 0.0,
  "verdict_change": "same" | "softer" | "stronger"
}
If the evidence is weak or mismatched, lower confidence and set verdict_change to "softer".
Use [DOI] or [Author et al.] citations where available."""

_QA_SYSTEM = """You are an expert MOF (Metal-Organic Framework) scientist specialising in CO2 capture.
Answer questions using the provided context from extracted papers and database records.
Context sections: SOURCE A (extracted paper full text), SOURCE B (MOF database), SOURCE C (web abstracts), SOURCE D (live-fetched full text), SOURCE E (past query findings — useful background but not primary evidence).
Always cite sources using paper title or DOI when the information comes from literature.
Be precise: include units, temperature (K), and pressure (bar) when reporting uptake or selectivity values.
If context does not contain enough information to answer confidently, say so explicitly."""

_CHITCHAT_SYSTEM = """You are MOF Scout, an AI research assistant specialising in Metal-Organic Frameworks for CO2 capture.
You help scientists discover, compare, and analyse MOF materials for carbon capture applications.
Be friendly and concise. If the user shifts to a research question or hypothesis, encourage them to use Q&A or Hypothesis mode."""


# ── Public API ─────────────────────────────────────────────────────────────────

def dispatch(query: str, history: list[dict] | None = None, mode: str = "auto",
             deepread_n: int = 3) -> dict:
    """Route query to the correct pipeline and return a unified result dict."""
    if mode == "auto":
        intent = route_intent(query)
    elif mode in ("hypothesis", "question", "chitchat"):
        intent = mode
    else:
        intent = "question"

    if intent == "hypothesis":
        result = test_hypothesis(query, deepread_n=deepread_n)
    elif intent == "chitchat":
        result = chitchat(query)
    else:
        result = answer_question(query, history or [], deepread_n=deepread_n)

    result["intent"] = intent
    return result


def route_intent(query: str) -> str:
    """Single-token classification: hypothesis | question | chitchat."""
    raw = _llm_call_simple(query, _INTENT_SYSTEM, max_tokens=10, temperature=0.0)
    if raw:
        word = raw.strip().lower().split()[0]
        if word in ("hypothesis", "question", "chitchat"):
            return word
    # heuristic fallback
    q = query.lower()
    if any(k in q for k in ("?", "what ", "which ", "how ", "when ", "where ", "does ", "do ", "is ", "are ")):
        return "question"
    if any(k in q for k in ("mofs with", "higher ", "better ", "more ", "less ", "show ", "capture ", "i think", "hypothesis")):
        return "hypothesis"
    return "question"


def answer_question(query: str, history: list[dict] | None = None,
                    n_chunks: int = 6, deepread_n: int = 3) -> dict:
    """Cited answer using RAG + DB + live web search + optional full-text deepread."""
    trace: list[dict] = []
    t_total = _ts()

    t = _ts(); memories, q_emb = _recall_memory(query)
    _step(trace, "memory_recall", t, found=len(memories))

    t = _ts(); rag_chunks = retrieve(query, n_results=n_chunks)
    _step(trace, "rag_retrieve", t, chunks=len(rag_chunks))

    t = _ts(); db_mofs, _ = query_mofs(search=query, limit=10)
    _step(trace, "db_query", t, rows=len(db_mofs))

    t = _ts(); web_papers = _live_search(query, limit=5)
    _step(trace, "web_search", t, papers=len(web_papers))

    t = _ts(); deepread = _deepread_papers(web_papers, query, deepread_n)
    _step(trace, "deepread", t, fetched=len(deepread))

    all_web     = _merge_deepread(web_papers, deepread)
    relevant_db = _filter_relevant_mofs(db_mofs)
    context     = _build_context(rag_chunks, relevant_db, all_web, memories=memories)

    messages = _build_history(history or [])
    messages.append({"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"})

    t = _ts(); answer = _llm_call_messages(_QA_SYSTEM, messages, max_tokens=2000) or ""
    _step(trace, "llm_answer", t)

    sources = _build_unified_sources(rag_chunks, all_web)
    [answer], sources = _number_citations([answer], sources)

    _save_memory(query, "question", answer[:600], q_emb)

    return {
        "answer": answer or "No answer available — check that papers have been extracted and indexed.",
        "sources": sources,
        "db_mofs": relevant_db,
        "source_mix": {
            "paper_chunks": len(rag_chunks),
            "database_records": len(relevant_db),
            "uses_rag": bool(rag_chunks),
            "uses_mof_database": bool(relevant_db),
        },
        "trace": trace,
        "trace_total_ms": round((time.perf_counter() - t_total) * 1000),
    }


def test_hypothesis(hypothesis: str, n_chunks: int = 8, deepread_n: int = 3) -> dict:
    """
    3-stage hypothesis evaluation:
      Stage 1 — gather DB records + RAG chunks + live web search + deepread
      Stage 2 — Reasoning Agent: preliminary verdict
      Stage 3 — Critic Agent: challenges and revises confidence
    """
    trace: list[dict] = []
    t_total = _ts()

    t = _ts(); memories, q_emb = _recall_memory(hypothesis)
    _step(trace, "memory_recall", t, found=len(memories))

    # Stage 1 — evidence gathering
    t = _ts(); search_queries = _expand_hypothesis_queries(hypothesis)
    _step(trace, "query_expansion", t, queries=len(search_queries))

    t = _ts()
    raw_papers: list[dict] = []
    seen_keys: set[str] = set()
    for q in search_queries:
        for p in _live_search(q, limit=5):
            key = (p.get("doi") or p.get("title") or "").lower().strip()
            if key and key not in seen_keys:
                seen_keys.add(key)
                raw_papers.append(p)
    _step(trace, "web_search", t, papers=len(raw_papers))

    t = _ts(); web_papers = _rerank_by_similarity(hypothesis, raw_papers)[:8]
    _step(trace, "rerank", t, kept=len(web_papers))

    t = _ts(); rag_chunks = retrieve(hypothesis, n_results=n_chunks)
    _step(trace, "rag_retrieve", t, chunks=len(rag_chunks))

    t = _ts(); db_mofs, _ = query_mofs(search=hypothesis, limit=15)
    _step(trace, "db_query", t, rows=len(db_mofs))

    t = _ts(); deepread = _deepread_papers(web_papers, hypothesis, deepread_n)
    _step(trace, "deepread", t, fetched=len(deepread))

    all_web     = _merge_deepread(web_papers, deepread)
    relevant_db = _filter_relevant_mofs(db_mofs)
    context     = _build_context(rag_chunks, relevant_db, all_web, memories=memories)

    # Stage 2 — Reasoning Agent
    t = _ts()
    reasoning_raw = _llm_call_simple(
        f"Context:\n{context}\n\nHypothesis to evaluate: {hypothesis}",
        _REASONING_SYSTEM, max_tokens=2000, json_mode=True,
    )
    _step(trace, "reasoning_agent", t)
    try:
        reasoning = json.loads(_strip_fences(reasoning_raw or "{}"))
    except Exception:
        reasoning = {
            "status": "error", "summary": reasoning_raw or "Reasoning failed.",
            "reasons_for": [], "reasons_against": [], "data_gaps": [], "confidence": 0.0,
        }

    # Stage 3 — Critic Agent
    critic_input = (
        f"Original hypothesis: {hypothesis}\n\n"
        f"Reasoning agent verdict:\n{json.dumps(reasoning, indent=2)}\n\n"
        f"Supporting context:\n{context}"
    )
    t = _ts()
    critic_raw = _llm_call_simple(
        critic_input, _CRITIC_SYSTEM, max_tokens=1500, json_mode=True,
    )
    _step(trace, "critic_agent", t)
    try:
        critic = json.loads(_strip_fences(critic_raw or "{}"))
    except Exception:
        critic = {
            "challenges": [], "overlooked_evidence": [],
            "revised_confidence": reasoning.get("confidence", 0.0), "verdict_change": "same",
        }

    # Merge: apply critic's verdict_change to final status
    revised_confidence = critic.get("revised_confidence") or reasoning.get("confidence", 0.0)
    final_status = reasoning.get("status", "insufficient_data")
    verdict_change = critic.get("verdict_change", "same")
    if verdict_change == "softer" and final_status == "supported":
        final_status = "partially_supported"
    elif verdict_change == "stronger" and final_status == "partially_supported":
        final_status = "supported"

    # Number citations across all text fields
    sources = _build_unified_sources(rag_chunks, all_web)
    all_texts = (
        [reasoning.get("summary", "")]
        + reasoning.get("reasons_for", [])
        + reasoning.get("reasons_against", [])
        + reasoning.get("data_gaps", [])
        + critic.get("challenges", [])
        + critic.get("overlooked_evidence", [])
    )
    numbered, sources = _number_citations(all_texts, sources)
    n = len(reasoning.get("reasons_for", []))
    n2 = len(reasoning.get("reasons_against", []))
    n3 = len(reasoning.get("data_gaps", []))
    n4 = len(critic.get("challenges", []))
    summary_n       = numbered[0]
    reasons_for_n   = numbered[1 : 1+n]
    reasons_against_n = numbered[1+n : 1+n+n2]
    data_gaps_n     = numbered[1+n+n2 : 1+n+n2+n3]
    challenges_n    = numbered[1+n+n2+n3 : 1+n+n2+n3+n4]
    overlooked_n    = numbered[1+n+n2+n3+n4:]

    _save_memory(hypothesis, "hypothesis", summary_n[:600], q_emb)

    return {
        "status": final_status,
        "summary": summary_n,
        "reasons_for": reasons_for_n,
        "reasons_against": reasons_against_n,
        "data_gaps": data_gaps_n,
        "confidence": revised_confidence,
        "critic_challenges": challenges_n,
        "overlooked_evidence": overlooked_n,
        "sources": sources,
        "db_mofs": relevant_db,
        "trace": trace,
        "trace_total_ms": round((time.perf_counter() - t_total) * 1000),
    }


def chitchat(message: str) -> dict:
    """MOF-aware conversational response."""
    answer = _llm_call_simple(message, _CHITCHAT_SYSTEM, max_tokens=400)
    return {
        "answer": answer or "Hello! I'm MOF Scout. Ask me anything about MOF CO2 capture research.",
        "sources": [],
        "db_mofs": [],
    }


# ── Context builder ────────────────────────────────────────────────────────────

def _number_citations(texts: list[str], sources: list[dict]) -> tuple[list[str], list[dict]]:
    """
    Replace [DOI] / [Author et al., Year] citations in text fields with [1], [2], ...
    Skips internal DB references like [CoRE MOF: ...] and [DB literature: ...].
    Adds citation_number to matching sources.
    Returns (numbered_texts, updated_sources).
    """
    _DB_PREFIX = ("core mof:", "db literature:", "coremof:", "dbliterature:")
    cit_pattern = re.compile(r'\[([^\[\]\n]{3,120})\]')

    # Collect unique paper citations in order of first appearance across all text fields
    order: list[str] = []
    seen: dict[str, int] = {}
    for text in texts:
        for m in cit_pattern.finditer(text or ""):
            key = m.group(1).strip()
            if any(key.lower().startswith(p) for p in _DB_PREFIX):
                continue
            if key not in seen:
                seen[key] = len(order) + 1
                order.append(key)

    if not seen:
        return texts, sources

    def _replace(m: re.Match) -> str:
        key = m.group(1).strip()
        if any(key.lower().startswith(p) for p in _DB_PREFIX):
            return m.group(0)
        num = seen.get(key)
        return f"[{num}]" if num else m.group(0)

    numbered = [cit_pattern.sub(_replace, t or "") for t in texts]

    # Match each citation key back to a source by DOI or partial title
    sources = [dict(s) for s in sources]  # shallow copy to avoid mutation
    for s in sources:
        doi   = (s.get("doi") or "").strip().lower()
        title = (s.get("title") or "").strip().lower()
        for key, num in seen.items():
            kl = key.lower().strip()
            # DOI match
            if doi and (doi in kl or kl in doi or kl == doi):
                s["citation_number"] = num
                break
            # Title keyword overlap (≥3 significant words)
            if title and len(title) > 15:
                t_words = {w for w in re.split(r'\W+', title) if len(w) > 3}
                k_words = {w for w in re.split(r'\W+', kl)   if len(w) > 3}
                if len(t_words & k_words) >= 3:
                    s["citation_number"] = num
                    break

    return numbered, sources


def _deepread_papers(web_papers: list[dict], query: str, n: int = 3) -> list[dict]:
    """
    Fetch full text for the top-N most relevant web papers and return query-relevant
    chunks. No LLM call — just network fetch + text chunking + embedding retrieval.
    Papers are tried in relevance order (from _rerank_by_similarity); we attempt up to
    n*5 candidates so that fetch failures don't prevent hitting the quota.
    """
    if n <= 0 or not web_papers:
        return []

    # Keep relevance order — papers are already sorted by _rerank_by_similarity.
    # Only skip papers that have neither a DOI nor an OA PDF (nothing to resolve).
    candidates = [p for p in web_papers if p.get("doi") or p.get("open_access_pdf")][:n * 5]

    results: list[dict] = []
    for paper in candidates:
        if len(results) >= n:
            break
        title = (paper.get("title") or "").strip()

        try:
            text, _msg, method = resolve_fulltext(paper)
        except Exception as e:
            logger.info("deepread fetch failed '%s': %s", title[:50], e)
            continue

        if not text or len(text) < 2000:
            logger.info("deepread: text too short for '%s' (%d chars)", title[:50], len(text or ""))
            continue

        if method == "pmc_xml":
            try:
                text = pmc_xml_to_text(text)
            except Exception:
                pass

        chunks = _retrieve_relevant_chunks(text, query)
        if not chunks:
            continue

        logger.info("deepread: got %d chunks from '%s' (%d chars total)", len(chunks), title[:50], len(text))
        results.append({**paper, "relevant_chunks": chunks, "deepread": True})

    return results


def _merge_deepread(web_papers: list[dict], deepread: list[dict]) -> list[dict]:
    """Return web_papers list with deepread entries replacing their original (by doi/title)."""
    if not deepread:
        return web_papers
    dr_keys = {(p.get("doi") or p.get("title") or "").lower().strip() for p in deepread}
    merged = list(deepread)
    for p in web_papers:
        key = (p.get("doi") or p.get("title") or "").lower().strip()
        if key not in dr_keys:
            merged.append(p)
    return merged


def _retrieve_relevant_chunks(text: str, query: str, top_k: int = 5) -> list[str]:
    """
    Chunk full text and retrieve the top_k most semantically similar chunks using
    text-embedding-3-small (same model as the RAG store). Falls back to keyword
    scoring when no OpenAI key is available.
    """
    import numpy as np

    chunks = chunk_text(text)
    if not chunks:
        return []

    # ── Embedding-based retrieval ───────────────────────────────────────────────
    embeddings = embed_texts([query] + chunks)
    if embeddings and len(embeddings) == len(chunks) + 1:
        vecs = np.array(embeddings, dtype=np.float32)
        # L2-normalise so dot product == cosine similarity
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        vecs /= norms
        q_vec   = vecs[0]
        c_vecs  = vecs[1:]
        scores  = c_vecs @ q_vec          # shape (n_chunks,)
        top_idx = scores.argsort()[::-1][:top_k]
        # Return in document order (preserves narrative flow)
        top_idx_sorted = sorted(top_idx)
        return [chunks[i] for i in top_idx_sorted]

    # ── Keyword fallback (no API key) ──────────────────────────────────────────
    terms = {w.lower() for w in re.split(r'\W+', query) if len(w) > 2}
    terms.update({w for w in re.split(r'\W+', query.lower())
                  if w in ("co2", "mof", "mofs", "dac", "co₂", "n2", "ch4")})
    scored = sorted(enumerate(chunks),
                    key=lambda ic: sum(1 for t in terms if t in ic[1].lower()),
                    reverse=True)
    top_idx = sorted(i for i, _ in scored[:top_k])
    return [chunks[i] for i in top_idx]


# ── Trace helpers ──────────────────────────────────────────────────────────────

def _ts() -> float:
    return time.perf_counter()


def _step(trace: list[dict], name: str, t0: float, **data) -> None:
    trace.append({"name": name, "ms": round((time.perf_counter() - t0) * 1000), **data})


# ── Agent memory helpers ────────────────────────────────────────────────────────

def _recall_memory(query: str) -> tuple[list[dict], list[float]]:
    """Embed query, find semantically similar past responses. Returns (memories, q_embedding)."""
    embeddings = embed_texts([query])
    if not embeddings:
        return [], []
    q_emb = embeddings[0]
    memories = search_agent_memory(q_emb, top_k=3, min_similarity=0.72)
    return memories, q_emb


def _save_memory(query: str, intent: str, summary: str, q_emb: list[float]) -> None:
    """Persist a condensed finding to agent memory (non-blocking, errors are swallowed)."""
    if not summary.strip():
        return
    try:
        emb = q_emb or (embed_texts([query]) or [[]])[0]
        if emb:
            save_agent_memory(query, intent, summary[:600], emb)
    except Exception as e:
        logger.warning("save_agent_memory failed: %s", e)


def _expand_hypothesis_queries(hypothesis: str) -> list[str]:
    """
    Use a fast LLM call to decompose a hypothesis into 2-3 targeted search queries.
    Each query focuses on a specific aspect: material+property, mechanism, or condition.
    Falls back to the raw hypothesis if the LLM call fails.
    """
    system = (
        "You are a MOF research librarian. Given a scientific hypothesis, produce 3 short "
        "keyword search queries (4-8 words each) that would find the most directly relevant papers.\n"
        "Cover:\n"
        "  1. The specific material + property (e.g. 'MOF-5 water stability degradation')\n"
        "  2. The claimed mechanism (e.g. 'zinc carboxylate bond hydrolysis MOF')\n"
        "  3. The experimental evidence needed (e.g. 'MOF-5 humidity XRD FTIR decomposition')\n"
        "Use scientific terminology only. Return JSON: {\"queries\": [\"q1\", \"q2\", \"q3\"]}"
    )
    try:
        raw = _llm_call_simple(hypothesis, system, max_tokens=150,
                               temperature=0.0, json_mode=True)
        data = json.loads(_strip_fences(raw or "{}"))
        queries = [q.strip() for q in (data.get("queries") or []) if isinstance(q, str) and q.strip()]
        if queries:
            logger.info("hypothesis queries: %s", queries)
            return queries[:3]
    except Exception as e:
        logger.warning("query expansion failed: %s", e)
    return [hypothesis]


def _rerank_by_similarity(hypothesis: str, papers: list[dict]) -> list[dict]:
    """
    Re-rank papers by cosine similarity between the hypothesis embedding and each
    paper's abstract (falling back to title). Uses text-embedding-3-small.
    Papers with no abstract or title are placed at the end.
    """
    import numpy as np

    texts = [p.get("abstract") or p.get("title") or "" for p in papers]
    embeddings = embed_texts([hypothesis] + texts)
    if not embeddings or len(embeddings) != len(papers) + 1:
        return papers  # fallback: keep original order

    vecs = np.array(embeddings, dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    vecs /= norms
    scores = vecs[1:] @ vecs[0]          # cosine similarity of each abstract to hypothesis

    ranked = sorted(zip(scores.tolist(), papers), key=lambda x: -x[0])
    for score, paper in ranked:
        paper["_relevance"] = round(float(score), 4)
    return [p for _, p in ranked]


def _live_search(query: str, limit: int = 5) -> list[dict]:
    """Search Semantic Scholar + PubMed + OpenAlex; return lightweight dicts with abstract."""
    try:
        papers = search_all(query, limit=limit, sort_by="relevance")
        return [
            {
                "title":           p.get("title", ""),
                "abstract":        (p.get("abstract") or "")[:800],
                "doi":             p.get("doi", ""),
                "url":             p.get("url", ""),
                "open_access_pdf": p.get("open_access_pdf", ""),
                "year":            p.get("year"),
                "citationCount":   p.get("citationCount", 0),
                "authors":         p.get("authors", [])[:3],
                "source":          p.get("source", "web"),
            }
            for p in papers
            if p.get("title")
        ]
    except Exception as e:
        logger.warning("Live search failed: %s", e)
        return []


def _build_context(rag_chunks: list[dict], db_mofs: list[dict],
                   web_papers: list[dict] | None = None,
                   memories: list[dict] | None = None) -> str:
    parts: list[str] = []

    # ── Source A: full text from locally extracted papers (highest quality) ──
    if rag_chunks:
        parts.append("=== SOURCE A: Full-text excerpts from extracted papers (cite by DOI or title) ===")
        for c in rag_chunks:
            label = c.get("doi") or c.get("title") or "Unknown"
            parts.append(f"[{label}]\n{c['text']}")
    else:
        parts.append("=== SOURCE A: No locally extracted papers indexed yet ===")

    # ── Source B: MOF database records (CoRE MOF + literature) ──
    if db_mofs:
        core  = [m for m in db_mofs if m["source"] == "core_mof"]
        lit   = [m for m in db_mofs if m["source"] == "literature"]
        parts.append(f"\n=== SOURCE B: MOF database ({len(core)} CoRE MOF, {len(lit)} literature records) ===")
        for m in db_mofs:
            src_tag = "CoRE MOF" if m["source"] == "core_mof" else "literature"
            line = f"• {m['name']} [{src_tag}]"
            if m.get("surface_area_m2_g"):
                line += f" | SA: {m['surface_area_m2_g']:.0f} m²/g"
            if m.get("pore_volume_cm3_g"):
                line += f" | PV: {m['pore_volume_cm3_g']:.3f} cm³/g"
            if m.get("pore_limiting_diameter_A"):
                line += f" | PLD: {m['pore_limiting_diameter_A']:.1f} Å"
            if m.get("void_fraction"):
                line += f" | VF: {m['void_fraction']:.3f}"
            if m.get("henry_law_co2_class"):
                line += f" | KH class: {m['henry_law_co2_class']}"
            if m.get("water_stability"):
                line += f" | H₂O stability: {m['water_stability']}"
            if m.get("thermal_stability_c"):
                line += f" | thermal: {m['thermal_stability_c']}°C"
            if m.get("has_open_metal_site") is not None:
                line += f" | OMS: {'yes' if m['has_open_metal_site'] else 'no'}"
            if m.get("topology"):
                line += f" | topo: {m['topology']}"
            parts.append(line)
            for ms in (m.get("measurements") or [])[:6]:
                mline = f"  ↳ [{src_tag}] {ms['measurement_type']}: {ms['value']} {ms.get('unit','')}"
                if ms.get("temperature_k"):
                    mline += f" @{ms['temperature_k']}K"
                if ms.get("pressure_bar"):
                    mline += f"/{ms['pressure_bar']}bar"
                if ms.get("selectivity_definition"):
                    mline += f" ({ms['selectivity_definition']})"
                if ms.get("application_type"):
                    mline += f" [{ms['application_type']}]"
                if ms.get("evidence_quote"):
                    mline += f' — "{ms["evidence_quote"][:120]}"'
                parts.append(mline)
            if not m.get("measurements") and m.get("co2_uptake_value"):
                line2 = f"  ↳ [CoRE MOF] co2_uptake: {m['co2_uptake_value']} {m.get('co2_uptake_unit','')}"
                if m.get("temperature_k"):
                    line2 += f" @{m['temperature_k']}K/{m.get('pressure_bar','')}bar"
                parts.append(line2)
    else:
        parts.append("\n=== SOURCE B: No relevant MOF database records found for this query ===")

    # ── Source C: web abstracts (non-deepread papers only) ──
    abstract_papers = [p for p in (web_papers or []) if not p.get("deepread") and p.get("abstract")]
    deepread_papers = [p for p in (web_papers or []) if p.get("deepread") and p.get("relevant_chunks")]

    if abstract_papers:
        parts.append("\n=== SOURCE C: Web search — recent paper abstracts (cite by DOI) ===")
        for p in abstract_papers:
            label = p.get("doi") or p.get("title") or "Unknown"
            authors = ", ".join((p.get("authors") or [])[:2])
            parts.append(f"[{label} | {authors} | {p.get('year', '')}]\n{p['abstract']}")
    else:
        parts.append("\n=== SOURCE C: No additional web abstracts ===")

    # ── Source D: query-relevant excerpts retrieved from live-fetched full texts ──
    if deepread_papers:
        parts.append("\n=== SOURCE D: Full-text excerpts from live-fetched papers — treat as SOURCE A (cite by DOI) ===")
        for p in deepread_papers:
            label = p.get("doi") or p.get("title") or "Unknown"
            authors = ", ".join((p.get("authors") or [])[:2])
            excerpts = "\n\n[…]\n\n".join(p["relevant_chunks"])
            parts.append(f"[{label} | {authors} | {p.get('year', '')}]\n{excerpts}")
    else:
        parts.append("\n=== SOURCE D: No live full-text papers fetched ===")

    # ── Source E: condensed findings from past related queries ──
    if memories:
        parts.append("\n=== SOURCE E: Condensed findings from previous related queries (background context only) ===")
        for m in memories:
            parts.append(f"[Past query (similarity {m['similarity']}): {m['query']}]\n{m['summary']}")
    else:
        parts.append("\n=== SOURCE E: No related past queries found ===")

    return "\n\n".join(parts)


def _build_history(history: list[dict]) -> list[dict]:
    """Convert frontend history items to OpenAI messages format, capped at last 10 turns."""
    messages = []
    for h in history[-10:]:
        role = h.get("role", "user")
        content = h.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    return messages


def _build_unified_sources(rag_chunks: list[dict], web_papers: list[dict]) -> list[dict]:
    """Merge local extracted-paper chunks and web search papers into one deduplicated list."""
    seen: set[str] = set()
    out: list[dict] = []

    for c in rag_chunks:
        key = (c.get("doi") or c.get("title") or "").lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append({
                "title":       c.get("title", ""),
                "doi":         c.get("doi", ""),
                "url":         c.get("doi") and f"https://doi.org/{c['doi']}" or "",
                "score":       c["score"],
                "source_type": "extracted",
                "abstract":    "",
                "year":        None,
                "authors":     [],
            })

    for p in web_papers:
        key = (p.get("doi") or p.get("title") or "").lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append({
                "title":              p.get("title", ""),
                "doi":                p.get("doi", ""),
                "url":                p.get("url", "") or (p.get("doi") and f"https://doi.org/{p['doi']}") or "",
                "open_access_pdf":    p.get("open_access_pdf", ""),
                "score":              0.0,
                "source_type":        "web",
                "web_source":         p.get("source", "web"),
                "abstract":           p.get("abstract", ""),
                "year":               p.get("year"),
                "authors":            p.get("authors", []),
                "citationCount":      p.get("citationCount", 0),
                "deepread":           p.get("deepread", False),
            })

    # Sort: extracted first (they have actual full text), then web by citation count
    out.sort(key=lambda s: (0 if s["source_type"] == "extracted" else 1, -s.get("citationCount", 0)))
    return out


def _filter_relevant_mofs(mofs: list[dict]) -> list[dict]:
    """Keep only MOF records that have actual CO2 performance or structural data worth showing."""
    relevant = []
    for m in mofs:
        has_perf = (
            m.get("co2_uptake_value") is not None
            or m.get("selectivity_value") is not None
            or m.get("henry_law_co2_class")
            or any(ms.get("value") is not None for ms in (m.get("measurements") or []))
        )
        has_struct = (
            m.get("surface_area_m2_g") is not None
            or m.get("pore_limiting_diameter_A") is not None
            or m.get("void_fraction") is not None
        )
        if has_perf or has_struct:
            relevant.append(m)
    return relevant[:10]


# ── LLM helpers ───────────────────────────────────────────────────────────────

def _llm_call_simple(user_msg: str, system: str, max_tokens: int = 2000,
                     temperature: float = 0.2, json_mode: bool = False) -> str | None:
    return _llm_call_messages(
        system, [{"role": "user", "content": user_msg}],
        max_tokens=max_tokens, temperature=temperature, json_mode=json_mode,
    )


def _llm_call_messages(system: str, messages: list[dict], max_tokens: int = 2000,
                       temperature: float = 0.2, json_mode: bool = False) -> str | None:
    if OPENAI_API_KEY:
        extra = {"response_format": {"type": "json_object"}} if json_mode else {}
        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                         "Content-Type": "application/json"},
                json={"model": OPENAI_MODEL,
                      "messages": [{"role": "system", "content": system}] + messages,
                      "temperature": temperature, "max_tokens": max_tokens, **extra},
                timeout=90,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error("OpenAI error: %s", e)

    if GROQ_KEY:
        from groq import Groq
        try:
            resp = Groq(api_key=GROQ_KEY).chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "system", "content": system}] + messages,
                temperature=temperature, max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.error("Groq error: %s", e)

    return None


def _strip_fences(raw: str) -> str:
    idx = raw.find("```")
    if idx != -1:
        raw = raw[idx + 3:].strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
        end = raw.find("```")
        if end != -1:
            raw = raw[:end].strip()
    return raw
