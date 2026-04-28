# MOF Discovery

A full-stack research tool for discovering, extracting, and reasoning about Metal-Organic Framework (MOF) CO₂ capture data.

**What it does:**

- Searches Semantic Scholar, PubMed, and OpenAlex simultaneously for MOF papers
- Fetches full text via Unpaywall, PMC XML, EuropePMC, RSC articlehtml, publisher HTML, or direct PDF
- Extracts structured MOF records (CO₂ uptake, selectivity, working capacity, structural properties) from full papers using GPT-4o
- Stores everything in a unified SQLite database alongside ~2,500 CoRE MOF simulation records
- Indexes extracted paper text into a ChromaDB vector store for semantic RAG
- Answers research questions and evaluates hypotheses using a multi-source pipeline: extracted-paper RAG + CoRE MOF DB + live web search + full-text deepread
- Recalls condensed findings from past related queries via embedding-based agent memory

---

## Origin

This project is the production evolution of the prototype built in [`stats-sisters-accenture/prod/`](https://github.com/ts3424/stats-sisters-accenture).

The following were referenced and carried forward from that repository:

**Agent architecture** — the 3-pipeline intent router (hypothesis / Q&A / chitchat), the Reasoning Agent + Critic Agent structure for hypothesis evaluation, and the cited Q&A pipeline with conversation memory all originate from `prod/src/agent/`.

**Extraction pipeline** — the overall flow (search → resolve full text → LLM extraction → SQLite upsert) and the multi-strategy full-text resolver (Unpaywall → PMC XML → curl_cffi → Playwright) originate from `prod/src/extraction/`. The Pydantic schemas (`MOFRecord`, `PaperMeta`, `ExtractionResult`) and the chunked extraction fallback are also from there.

**MOF data schema** — the unified `mofs` table structure (structural fields, CO₂ uptake, selectivity, working capacity, application type, evidence quote, confidence score) was designed in `prod/` and extended here with a separate `mof_measurements` table for multi-condition records.

**CoRE MOF data** — `FSR_data_SI_20250204.csv` and `ASR_data_SI_20250204.csv` from `CoRE_MOF_Data/` in that repo (~2,500 structures with pore geometry, stability scores, and Henry-law CO₂ class).

**Paper search** — the Semantic Scholar search and abstract normalisation logic originates from `prod/src/extraction/search.py` and individual preliminary scripts (`becc_prelim/`, `pris_prelim/`). PubMed and OpenAlex were added in this repo.

What changed: the Streamlit UI was replaced with React + Vite, the backend became a FastAPI server with SSE streaming, ChromaDB was added for semantic RAG, and the Ask pipeline was extended with live web search, hypothesis query decomposition, embedding-based re-ranking, full-text deepread, numbered citations, agent memory, and a pipeline trace.

---

## Requirements

- Python 3.10+
- Node.js 18+
- `OPENAI_API_KEY` — required for extraction (GPT-4o) and embeddings (text-embedding-3-small)
- `GROQ_KEY` — optional fallback for extraction when OpenAI hits rate limits

---

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/hanna0601/mof-discovery.git
cd mof-discovery
cp .env.example .env
```

Open `.env` and fill in your keys (see [API Keys](#api-keys) below).

### 2. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium      # fallback for JS-heavy publisher pages
```

### 3. Frontend

```bash
cd frontend
npm install
```

### 4. Run

Open two terminals from the repo root:

**Terminal 1 — Backend:**

```bash
cd backend
source .venv/bin/activate
python3 -m uvicorn app:app --reload --port 8000
```

**Terminal 2 — Frontend:**

```bash
cd frontend
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

---

## API Keys

| Key | Required | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | **Yes** | GPT-4o for extraction; text-embedding-3-small for RAG, deepread retrieval, agent memory, and reranking |
| `GROQ_KEY` | No | Llama 4 as fallback if OpenAI rate-limits during extraction |
| `SEMANTIC_SCHOLAR_KEY` | No | Higher rate limits for paper search (works without it, just slower) |
| `NCBI_API_KEY` | No | Higher rate limits for PubMed search and PMC full-text fetch |
| `UNPAYWALL_EMAIL` | No | Enables Unpaywall OA PDF resolution (any valid email) |

---

## Import CoRE MOF Data

With the backend running, import the ASR and FSR CSV files:

```bash
curl -X POST "http://localhost:8000/api/mofs/import-core-directory?directory_path=/absolute/path/to/CoRE_MOF_Data"
```

Replace the path with the directory containing `FSR_data_SI_20250204.csv` and `ASR_data_SI_20250204.csv`. This imports ~2,500 rows into the `mofs` table with `source='core_mof'`.

---

## How It Works

### Pages

**Discover** — Search across Semantic Scholar, PubMed, and OpenAlex. Filter by year or date range. Check full-text availability before queuing papers for extraction.

**Extract** — Fetches full text using a multi-strategy resolver (Unpaywall → PMC XML → EuropePMC → RSC articlehtml → publisher HTML → Playwright → direct PDF). Sends full paper to GPT-4o for structured MOF extraction. Failed papers can have a PDF uploaded manually. Extracted papers are indexed into ChromaDB for semantic search.

**Database** — Browse all MOF records in one view. CoRE MOF rows have structural data (BET surface area, pore volume, pore-limiting diameter, void fraction, Henry-law CO₂ class, open metal sites, water/solvent/thermal stability). Literature rows have experimental measurements (CO₂ uptake, CO₂/N₂ selectivity, working capacity) with evidence quotes and confidence scores. Expand any row to see all measured conditions.

**Ask** — Multi-source Q&A and hypothesis evaluation. See [Ask Pipeline](#ask-pipeline) below.

### Ask Pipeline

Every query runs through five evidence sources and returns numbered citations, a collapsible pipeline trace, and is saved to agent memory for future related queries.

**Evidence sources:**

| Source | What it contains |
| --- | --- |
| A | Full-text chunks from locally extracted and indexed papers (ChromaDB RAG) |
| B | CoRE MOF simulation records + literature-extracted values from the SQLite database |
| C | Abstracts from a live Semantic Scholar + PubMed + OpenAlex search |
| D | Query-relevant excerpts retrieved from live-fetched full texts (deepread) |
| E | Condensed findings from past related queries, recalled by embedding similarity |

**Q&A mode:** retrieves RAG chunks + DB records + web abstracts + deepread excerpts, then generates a cited answer. Citations are numbered `[1]`, `[2]`, … and matched back to the source list.

**Hypothesis mode:**

1. Decomposes the hypothesis into 2–3 targeted keyword queries via a fast LLM call
2. Searches Semantic Scholar + PubMed + OpenAlex with each query
3. Re-ranks all retrieved papers by cosine similarity between their abstracts and the hypothesis embedding
4. Fetches full text of the top-N most relevant papers (deepread, default N=3, adjustable in the UI)
5. Runs a Reasoning Agent → Critic Agent pipeline

The Reasoning Agent applies a two-track evaluation protocol:

- **Material-specific hypotheses** (e.g. "MOF-5 degrades in humidity"): requires direct evidence on the same material, same condition, same mechanism. Strict confidence thresholds to prevent overclaiming.
- **General/methodological hypotheses** (e.g. "IAST selectivity predicts real performance ranking"): papers that explicitly validate the method against ground-truth measurements are classified as DIRECT evidence. A partially-validated method with consistent support warrants `partially_supported` rather than `insufficient_data`.

**Deepread:** no LLM call. The full paper text is fetched, chunked, and the top-K most relevant chunks are retrieved by embedding cosine similarity (text-embedding-3-small). Falls back to keyword scoring when no API key is set.

**Agent memory:** after each Q&A or hypothesis query, a condensed summary is embedded and stored in the `agent_memory` SQLite table. Future related queries (cosine similarity ≥ 0.72) receive the past findings as SOURCE E context.

**Pipeline trace:** a collapsible panel in the UI shows the time spent at each step — memory recall, RAG retrieve, DB query, web search, embedding rerank, full-text fetch, LLM calls — so you can see exactly where time is going.

### Full-text resolver

The resolver tries sources in this order, returning the first that yields ≥ 2,000 characters:

1. Unpaywall — preprint/repository PDF or OA landing page
2. PMC XML — NCBI eFetch structured XML (best quality for biomedical papers)
3. EuropePMC — separate corpus covering chemistry journals
4. RSC articlehtml — for `10.1039/` DOIs, follows the doi.org redirect and swaps `articlelanding` → `articlehtml` to get the full-text HTML instead of the abstract-only landing page
5. BS4 — plain requests + BeautifulSoup via doi.org redirect
6. curl_cffi — Chrome TLS fingerprint, bypasses Cloudflare
7. Publisher HTML — direct full-text URL for ACS (`/doi/full/`), Wiley (`/doi/full/`), Nature (`/articles/`)
8. Playwright — headless Chromium for JS-rendered pages (ScienceDirect, Springer)
9. PDF — download and parse with PyMuPDF

### Data Model

Both CoRE MOF and literature-extracted records share the same `mofs` table:

| Field | CoRE MOF | Literature |
| --- | --- | --- |
| `surface_area_m2_g` | ✅ BET/ASA | ✅ extracted |
| `pore_volume_cm3_g` | ✅ | ✅ |
| `pore_limiting_diameter_A` | ✅ | ✅ |
| `largest_cavity_diameter_A` | ✅ | ✅ |
| `void_fraction` | ✅ | ✅ |
| `has_open_metal_site` | ✅ | ✅ |
| `water_stability` | ✅ score | ✅ text |
| `thermal_stability_c` | ✅ | ✅ |
| `henry_law_co2_class` | ✅ simulation | — |
| `co2_uptake_value` | — | ✅ |
| `selectivity_value` | — | ✅ |
| `working_capacity_mmol_g` | — | ✅ |
| `application_type` | — | ✅ DAC / post_combustion / pre_combustion |

Individual measurement conditions (temperature, pressure, selectivity definition) are stored separately in `mof_measurements` and joined on read.

### Data Locations

| Resource | Default path |
| --- | --- |
| SQLite database | `backend/data/databases/mof.sqlite3` |
| ChromaDB vectors | `backend/data/vectors/` |
| Uploaded PDFs | `backend/data/uploads/` |

Override any path in `.env` using `MOF_DB_PATH`, `VECTOR_DB_PATH`, `UPLOADS_DIR`.

---

## Troubleshooting

**`No module named 'chromadb'`**
Run `pip install chromadb>=0.4.22` inside the venv. Without it the Ask page falls back to DB-only answers.

**Groq rate limits during extraction**
The chunked Groq fallback sleeps and retries on 429. Set `OPENAI_API_KEY` to use GPT-4o single-call extraction instead.

**Full-text fetch fails for a paper**
The resolver tries 9 strategies but some papers are paywalled. On the Extract page, click "Upload PDF" next to any failed paper to provide the file manually.

**RSC papers return only the abstract**
This happens if the resolver fetches the `articlelanding` URL instead of `articlehtml`. The fix is built in for `10.1039/` DOIs — it follows the doi.org redirect and swaps the URL automatically. If it still fails, check that `requests` can reach `pubs.rsc.org` from your machine.

**`playwright install` not run**
Without Chromium, JS-heavy publisher pages (ScienceDirect, ACS, Wiley) fall back to earlier strategies which may retrieve less text. Run `playwright install chromium` once per environment.

**CoRE MOF import — path not found**
The `import-core-directory` endpoint takes an absolute path on the machine running the backend. Use `$(pwd)` to get the current directory if needed.

**Deepread fetches irrelevant papers**
Papers are selected in relevance order (cosine similarity of abstract to query, via text-embedding-3-small). If no `OPENAI_API_KEY` is set, embeddings are unavailable and selection falls back to the original web-search ranking. Increase the "Full-read" slider in the Ask UI (default 3, max 5) to fetch more papers.

**Agent memory not recalling past queries**
Memory recall requires `OPENAI_API_KEY` for embeddings. Without it, `_recall_memory` returns empty and SOURCE E is omitted from context. Past queries are stored in the `agent_memory` table in the SQLite database.
