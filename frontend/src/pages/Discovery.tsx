import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, Filter, Plus, Minus, ArrowRight, BookOpen,
         Calendar, SortAsc, Database, AlertCircle, CheckCircle, XCircle, Gauge } from 'lucide-react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api'
import type { FullTextAssessment, Paper } from '../types'

const SOURCES = [
  { id: 'semantic_scholar', label: 'Semantic Scholar', color: 'badge-purple' },
  { id: 'pubmed',           label: 'PubMed',           color: 'badge-blue'   },
  { id: 'openalex',        label: 'OpenAlex',         color: 'badge-green'  },
]

const SOURCE_COLORS: Record<string, string> = {
  semantic_scholar: 'badge-purple',
  pubmed:           'badge-blue',
  openalex:         'badge-green',
}

interface Props {
  queue: Paper[]
  onAdd: (p: Paper) => void
  onRemove: (id: string) => void
}

export function Discovery({ queue, onAdd, onRemove }: Props) {
  const navigate = useNavigate()
  const [query,   setQuery]   = useState('')
  const [limit,   setLimit]   = useState(5)
  const [year,    setYear]    = useState<number | ''>('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [sortBy,  setSortBy]  = useState('relevance')
  const [sources, setSources] = useState(['semantic_scholar', 'pubmed', 'openalex'])
  const [showFilters, setShowFilters] = useState(false)
  const [assessments, setAssessments] = useState<Record<string, FullTextAssessment>>({})

  const search = useMutation({
    mutationFn: () => api.searchPapers({
      query, limit, year: year ? Number(year) : undefined,
      date_from: year ? undefined : dateFrom || undefined,
      date_to: year ? undefined : dateTo || undefined,
      sort_by: sortBy, sources,
    }),
  })

  const assess = useMutation({
    mutationFn: (papersToCheck: Paper[]) => api.assessPapers(papersToCheck),
    onSuccess: data => {
      const next: Record<string, FullTextAssessment> = {}
      data.assessments.forEach(a => { if (a.paperId) next[a.paperId] = a })
      setAssessments(s => ({ ...s, ...next }))
    },
  })

  const papers: Paper[] = search.data?.papers ?? []

  const toggleSource = (id: string) =>
    setSources(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id])

  const inQueue = (p: Paper) => queue.some(q => q.paperId === p.paperId)
  const selectedCanRun = queue.filter(p => assessments[p.paperId]?.can_extract !== false)

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <header className="px-8 pt-8 pb-6 border-b border-border">
        <div className="flex items-start justify-between gap-6">
          <div>
            <h1 className="text-2xl font-semibold text-slate-100 mb-1">Discover</h1>
            <p className="text-sm text-muted">
              Search Semantic Scholar, PubMed, and OpenAlex simultaneously. Check full-text availability, then queue papers for MOF extraction.
            </p>
          </div>
          <div className="hidden lg:grid grid-cols-3 gap-2 min-w-[330px]">
            <Metric label="Search" value={`${papers.length}`} />
            <Metric label="Queued" value={`${queue.length}`} />
            <Metric label="Full text" value={`${Object.values(assessments).filter(a => a.can_extract).length}`} />
          </div>
        </div>

        {/* Search bar */}
        <form onSubmit={e => { e.preventDefault(); if (query.trim()) search.mutate() }}
              className="mt-5 flex gap-2">
          <div className="relative flex-1">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="e.g. UiO-66 CO2 capture post-combustion..."
              className="input pl-9"
            />
          </div>
          <button type="submit" disabled={!query.trim() || search.isPending}
                  className="btn-primary min-w-[100px] justify-center">
            {search.isPending
              ? <span className="animate-spin border-2 border-white/30 border-t-white rounded-full w-4 h-4" />
              : <><Search size={14} /> Search</>}
          </button>
          <button type="button" onClick={() => setShowFilters(f => !f)}
                  className="btn-ghost border border-border">
            <Filter size={14} /> Filters
          </button>
        </form>

        {/* Filters */}
        <AnimatePresence>
          {showFilters && (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
              <div className="grid grid-cols-1 md:grid-cols-5 gap-4 mt-4 pt-4 border-t border-border">
                {/* Sources */}
                <div>
                  <div className="label mb-2 flex items-center gap-1"><Database size={10} /> Sources</div>
                  <div className="space-y-1.5">
                    {SOURCES.map(s => (
                      <label key={s.id} className="flex items-center gap-2 cursor-pointer">
                        <input type="checkbox" checked={sources.includes(s.id)}
                               onChange={() => toggleSource(s.id)}
                               className="w-3.5 h-3.5 rounded accent-teal-500" />
                        <span className="text-xs text-slate-300">{s.label}</span>
                      </label>
                    ))}
                  </div>
                </div>

                {/* Limit */}
                <div>
                  <div className="label mb-2">How many</div>
                  <div className="flex gap-1">
                    {[3, 5, 10, 15, 20].map(n => (
                      <button key={n} onClick={() => setLimit(n)}
                              className={`px-2.5 py-1 rounded text-xs font-medium border transition-all ${
                                limit === n
                                  ? 'bg-primary/20 border-primary text-cyan-200'
                                  : 'border-border text-muted hover:border-muted'
                              }`}>
                        {n}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Year */}
                <div>
                  <div className="label mb-2 flex items-center gap-1"><Calendar size={10} /> Year override</div>
                  <input type="number" placeholder="e.g. 2024" value={year}
                         onChange={e => setYear(e.target.value ? Number(e.target.value) : '')}
                         className="input w-full text-xs" />
                </div>

                <div>
                  <div className="label mb-2">From</div>
                  <input type="date" value={dateFrom} disabled={!!year}
                         onChange={e => setDateFrom(e.target.value)}
                         className="input w-full text-xs" />
                </div>

                <div>
                  <div className="label mb-2">To</div>
                  <input type="date" value={dateTo} disabled={!!year}
                         onChange={e => setDateTo(e.target.value)}
                         className="input w-full text-xs" />
                </div>

                {/* Sort */}
                <div>
                  <div className="label mb-2 flex items-center gap-1"><SortAsc size={10} /> Sort by</div>
                  <select value={sortBy} onChange={e => setSortBy(e.target.value)}
                          className="input w-full text-xs">
                    <option value="relevance">Relevance</option>
                    <option value="citations">Most Cited</option>
                    <option value="newest">Newest First</option>
                  </select>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </header>

      {/* Results */}
      <div className="flex-1 overflow-auto px-8 py-6">
        {/* Queue indicator */}
        {queue.length > 0 && (
          <motion.div initial={{ y: -10, opacity: 0 }} animate={{ y: 0, opacity: 1 }}
                      className="mb-4 flex items-center justify-between p-3 bg-primary/10 border border-primary/30 rounded-lg">
            <div className="text-sm text-cyan-200 font-medium">
              {queue.length} paper{queue.length > 1 ? 's' : ''} queued for extraction
              <span className="ml-2 text-xs text-muted">{selectedCanRun.length} currently eligible</span>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => assess.mutate(queue)}
                      disabled={assess.isPending || queue.length === 0}
                      className="btn-ghost border border-border text-xs py-1.5 px-3">
                <Gauge size={12} /> Check full text
              </button>
              <button onClick={() => navigate('/extract')}
                      className="btn-primary text-xs py-1.5 px-3">
                Go to Extraction <ArrowRight size={12} />
              </button>
            </div>
          </motion.div>
        )}

        {search.isError && (
          <div className="flex items-center gap-2 p-4 bg-danger/10 border border-danger/30 rounded-lg text-danger text-sm mb-4">
            <AlertCircle size={16} /> Search failed — check your API keys
          </div>
        )}

        {!search.data && !search.isPending && (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <BookOpen size={48} className="text-border mb-4" />
            <p className="text-muted">Enter a query to find relevant papers</p>
            <p className="text-xs text-muted/60 mt-1">Try "HKUST-1 CO2 selectivity" or "MIL-101 carbon capture"</p>
          </div>
        )}

        {papers.length === 0 && search.isSuccess && (
          <div className="text-center py-16 text-muted">No papers found — try a different query</div>
        )}

        <div className="space-y-3">
          <AnimatePresence>
            {papers.map((paper, i) => {
              const queued = inQueue(paper)
              const assessment = assessments[paper.paperId]
              return (
                <motion.div key={paper.paperId}
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: i * 0.04 }}
                            className={`card p-4 transition-all hover:border-border/80 ${
                              queued ? 'border-primary/40 bg-primary/5' : ''
                            }`}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      {/* Title + badges */}
                      <div className="flex items-start gap-2 flex-wrap mb-1">
                        <h3 className="text-sm font-semibold text-slate-100 leading-snug">
                          {paper.title}
                        </h3>
                      </div>
                      <div className="flex flex-wrap items-center gap-2 mb-2">
                        <span className={`${SOURCE_COLORS[paper.source] || 'badge-gray'} text-[10px]`}
                              style={{display:'inline-flex',alignItems:'center',gap:'2px',padding:'2px 6px',borderRadius:'9999px',fontSize:'10px',fontWeight:500}}>
                          {paper.source.replace(/_/g, ' ')}
                        </span>
                        {paper.authors.slice(0, 2).map((a, i) => (
                          <span key={i} className="text-xs text-muted">{a}</span>
                        ))}
                        {paper.authors.length > 2 && <span className="text-xs text-muted">et al.</span>}
                        {paper.year && <span className="text-xs text-muted">·  {paper.year}</span>}
                        {paper.citationCount > 0 && (
                          <span className="text-xs text-muted">· {paper.citationCount} citations</span>
                        )}
                        {paper.doi && (
                          <a href={`https://doi.org/${paper.doi}`} target="_blank" rel="noreferrer"
                             className="text-xs text-primary hover:underline">DOI</a>
                        )}
                        {assessment && (
                          <span className={`inline-flex items-center gap-1 text-xs ${
                            assessment.can_extract ? 'text-success' : 'text-danger'
                          }`}>
                            {assessment.can_extract ? <CheckCircle size={12} /> : <XCircle size={12} />}
                            {assessment.can_extract ? 'full paper' : assessment.quality}
                            {assessment.chars ? ` · ${(assessment.chars / 1000).toFixed(0)}k chars` : ''}
                          </span>
                        )}
                      </div>
                      {paper.abstract && (
                        <p className="text-xs text-muted line-clamp-2 leading-relaxed">
                          {paper.abstract}
                        </p>
                      )}
                    </div>

                    {/* Queue button */}
                    <button onClick={() => queued ? onRemove(paper.paperId) : onAdd(paper)}
                            disabled={false}
                            className={`flex-shrink-0 btn text-xs py-1.5 px-3 ${
                              queued
                                ? 'bg-primary/15 text-cyan-200 border border-primary/30 hover:bg-danger/10 hover:text-danger hover:border-danger/30'
                                : 'btn-ghost border border-border'
                            }`}>
                      {queued ? <><Minus size={12} /> Remove</> : <><Plus size={12} /> Queue</>}
                    </button>
                  </div>
                </motion.div>
              )
            })}
          </AnimatePresence>
        </div>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface/80 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-0.5 text-lg font-semibold text-slate-100">{value}</div>
    </div>
  )
}
