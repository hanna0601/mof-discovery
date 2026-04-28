import { useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Brain, Database, FileText, MessageCircle, Send, Sparkles,
  User, Loader2, ChevronDown, ChevronUp, Wand2, Bot, ExternalLink, Download, Activity,
} from 'lucide-react'
import { api } from '../api'
import type { AskResponse, Intent, AskSource, TraceStep } from '../types'

type Mode = 'auto' | 'question' | 'hypothesis' | 'chitchat'

interface HistoryItem {
  id: number
  query: string
  mode: Mode
  result: AskResponse
}

const INTENT_BADGE: Record<Intent, string> = {
  question:   'badge-blue',
  hypothesis: 'badge-purple',
  chitchat:   'badge-gray',
}

const INTENT_LABEL: Record<Intent, string> = {
  question:   'Q&A',
  hypothesis: 'Hypothesis',
  chitchat:   'Chitchat',
}

const STATUS_BADGE: Record<string, string> = {
  supported:           'badge-green',
  partially_supported: 'badge-amber',
  not_supported:       'badge-red',
  insufficient_data:   'badge-gray',
  error:               'badge-red',
}

export function AskPage() {
  const [query,      setQuery]      = useState('')
  const [mode,       setMode]       = useState<Mode>('auto')
  const [deepreadN,  setDeepreadsN] = useState(3)
  const [history,    setHistory]    = useState<HistoryItem[]>([])
  const idRef    = useRef(0)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Build flat history for API (last 10 turns, user+assistant pairs)
  const buildApiHistory = () => {
    const flat: { role: string; content: string }[] = []
    for (const item of history.slice(-10)) {
      flat.push({ role: 'user', content: item.query })
      if (item.result.answer) flat.push({ role: 'assistant', content: item.result.answer })
      else if (item.result.summary) flat.push({ role: 'assistant', content: item.result.summary })
    }
    return flat
  }

  const ask = useMutation({
    mutationFn: () => api.ask(query.trim(), mode, buildApiHistory(), deepreadN),
    onSuccess: (result: AskResponse) => {
      setHistory(h => [...h, { id: idRef.current++, query: query.trim(), mode, result }])
      setQuery('')
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 80)
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (query.trim() && !ask.isPending) ask.mutate()
  }

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-border px-8 pb-5 pt-8">
        <div className="flex items-start justify-between gap-6">
          <div>
            <h1 className="text-2xl font-semibold text-slate-100">Ask</h1>
            <p className="mt-1 text-sm text-muted">
              Ask a research question or test a hypothesis. Searches extracted-paper RAG, CoRE MOF + literature DB, and live web sources. Hypothesis mode runs a Reasoning Agent then a Critic Agent.
            </p>
          </div>
          <div className="flex items-center gap-1.5 text-[10px] text-muted">
            <Sparkles size={12} />
            <span>RAG · CoRE MOF · web search · deepread</span>
          </div>
        </div>

        {/* Mode toggle + deepread control */}
        <div className="mt-4 flex items-center gap-4 flex-wrap">
          <div className="grid w-80 grid-cols-4 rounded-lg border border-border bg-surface p-1">
            <ModeBtn label="Auto"       icon={<Wand2 size={13} />}         active={mode === 'auto'}       onClick={() => setMode('auto')} />
            <ModeBtn label="Q&A"        icon={<MessageCircle size={13} />} active={mode === 'question'}   onClick={() => setMode('question')} />
            <ModeBtn label="Hypothesis" icon={<Brain size={13} />}         active={mode === 'hypothesis'} onClick={() => setMode('hypothesis')} />
            <ModeBtn label="Chat"       icon={<Bot size={13} />}           active={mode === 'chitchat'}   onClick={() => setMode('chitchat')} />
          </div>
          <div className="flex items-center gap-2 text-xs text-muted">
            <FileText size={12} className="text-teal-400" />
            <span>Full-read</span>
            <select
              value={deepreadN}
              onChange={e => setDeepreadsN(Number(e.target.value))}
              className="rounded border border-border bg-surface px-1.5 py-0.5 text-xs text-slate-200 focus:outline-none"
            >
              {[0, 1, 2, 3, 4, 5].map(n => (
                <option key={n} value={n}>{n} paper{n !== 1 ? 's' : ''}</option>
              ))}
            </select>
          </div>
        </div>
      </header>

      {/* Conversation */}
      <div className="flex-1 overflow-auto px-8 py-6 space-y-6">
        {history.length === 0 && !ask.isPending && (
          <div className="flex h-full min-h-[300px] flex-col items-center justify-center text-center text-muted">
            <Brain size={44} className="mb-4 text-border" />
            <p className="text-sm">Ask a question, test a hypothesis, or just chat.</p>
            <p className="text-xs mt-1 text-muted/60">
              Auto mode detects intent and routes to the right pipeline.
            </p>
          </div>
        )}

        <AnimatePresence initial={false}>
          {history.map(item => (
            <motion.div key={item.id}
              initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
              className="space-y-3">

              {/* User bubble */}
              <div className="flex justify-end">
                <div className="flex items-start gap-2 max-w-2xl">
                  <div className="rounded-2xl rounded-tr-sm bg-primary/15 border border-primary/25 px-4 py-2.5">
                    <p className="text-sm text-slate-200 leading-relaxed">{item.query}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${INTENT_BADGE[item.result.intent]}`}>
                        {INTENT_LABEL[item.result.intent]}
                      </span>
                    </div>
                  </div>
                  <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <User size={14} className="text-cyan-300" />
                  </div>
                </div>
              </div>

              {/* Result */}
              <div className="flex justify-start">
                <div className="max-w-3xl w-full">
                  {item.result.intent === 'hypothesis'
                    ? <HypothesisResult data={item.result} />
                    : <QaResult data={item.result} />}
                </div>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {ask.isPending && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
            className="flex items-center gap-3 text-sm text-muted">
            <Loader2 size={16} className="animate-spin" />
            {deepreadN > 0
              ? `Fetching full text for up to ${deepreadN} paper${deepreadN !== 1 ? 's' : ''}, then reasoning…`
              : mode === 'hypothesis' || mode === 'auto'
                ? 'Running Reasoning Agent then Critic Agent...'
                : 'Retrieving paper chunks and database records...'}
          </motion.div>
        )}

        {ask.isError && (
          <div className="rounded-lg border border-danger/30 bg-danger/10 p-4 text-sm text-danger">
            Request failed — check backend logs and API keys.
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-border px-8 py-5">
        {history.length === 0 && (
          <div className="flex flex-wrap gap-2 mb-4">
            {EXAMPLE_PROMPTS.map(text => (
              <button key={text} onClick={() => setQuery(text)}
                className="rounded-lg border border-border bg-surface px-3 py-1.5 text-left text-xs text-muted hover:border-muted hover:text-slate-200 transition-colors">
                {text}
              </button>
            ))}
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex gap-3">
          <textarea
            rows={2}
            className="input flex-1 resize-none leading-relaxed"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (query.trim()) ask.mutate() }
            }}
            placeholder={
              mode === 'hypothesis' ? 'State a hypothesis, e.g. "MOFs with open metal sites show higher CO2 selectivity..."' :
              mode === 'chitchat'   ? 'Say anything...' :
              mode === 'question'   ? 'Ask about CO2 uptake, selectivity, stability, or conditions...' :
              'Ask a question, test a hypothesis, or just chat — intent is detected automatically.'
            }
          />
          <button type="submit" disabled={!query.trim() || ask.isPending}
            className="btn-primary self-end px-5">
            {ask.isPending ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
          </button>
        </form>
        <p className="mt-2 text-[10px] text-muted">Shift+Enter for newline · Enter to send</p>
      </div>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function ModeBtn({ label, icon, active, onClick }: {
  label: string; icon: React.ReactNode; active: boolean; onClick: () => void
}) {
  return (
    <button onClick={onClick}
      className={`flex items-center justify-center gap-1 rounded-md px-2 py-2 text-xs transition-all ${
        active ? 'bg-card text-slate-100 shadow-sm' : 'text-muted hover:text-slate-200'
      }`}>
      {icon} {label}
    </button>
  )
}

function QaResult({ data }: { data: AskResponse }) {
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-border bg-card px-5 py-4">
        <div className="prose-dark text-sm leading-relaxed">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {data.answer || 'No answer returned.'}
          </ReactMarkdown>
        </div>
      </div>
      <EvidencePanel data={data} />
      {data.trace && <TracePanel trace={data.trace} totalMs={data.trace_total_ms} />}
    </div>
  )
}

function HypothesisResult({ data }: { data: AskResponse }) {
  const badgeClass = STATUS_BADGE[data.status || 'error'] || STATUS_BADGE.insufficient_data
  return (
    <div className="space-y-3">
      {/* Verdict */}
      <div className="rounded-xl border border-border bg-card px-5 py-4">
        <div className="flex items-center gap-3 mb-3">
          <span className={badgeClass}>
            {String(data.status || 'unknown').replace(/_/g, ' ')}
          </span>
          {data.confidence !== undefined && (
            <span className="text-xs text-muted">
              confidence {Number(data.confidence).toFixed(2)}
            </span>
          )}
        </div>
        <p className="text-sm leading-relaxed text-slate-300">{data.summary}</p>
      </div>

      {/* Reasoning agent output */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <ListBlock title="For"        items={data.reasons_for}    accent="text-success" />
        <ListBlock title="Against"    items={data.reasons_against} accent="text-danger" />
        <ListBlock title="Data Gaps"  items={data.data_gaps}       accent="text-warning" />
      </div>

      {/* Critic agent output */}
      {((data.critic_challenges?.length ?? 0) > 0 || (data.overlooked_evidence?.length ?? 0) > 0) && (
        <div className="rounded-xl border border-border bg-card px-4 py-3">
          <div className="flex items-center gap-2 mb-2 text-xs font-semibold text-slate-200 uppercase tracking-wider">
            <Brain size={12} className="text-warning" /> Critic Agent
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <ListBlock title="Challenges"         items={data.critic_challenges}   accent="text-warning" />
            <ListBlock title="Overlooked Evidence" items={data.overlooked_evidence} accent="text-muted" />
          </div>
        </div>
      )}

      <EvidencePanel data={data} />
      {data.trace && <TracePanel trace={data.trace} totalMs={data.trace_total_ms} />}
    </div>
  )
}

function ListBlock({ title, items, accent }: { title: string; items?: string[]; accent: string }) {
  const [open, setOpen] = useState(true)
  if (!items?.length) return null
  return (
    <div className="rounded-xl border border-border bg-card px-4 py-3">
      <button onClick={() => setOpen(o => !o)}
        className="flex w-full items-center justify-between text-sm font-semibold text-slate-200 mb-2">
        <span className={accent}>{title}</span>
        {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </button>
      {open && (
        <ul className="space-y-1.5 text-xs text-slate-300">
          {items.map((item, i) => (
            <li key={i} className="flex gap-2">
              <span className={`${accent} mt-0.5 flex-shrink-0`}>·</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function EvidencePanel({ data }: { data: AskResponse }) {
  const sources = data.sources || []
  const mofs    = data.db_mofs || []
  const extracted = sources.filter(s => s.source_type === 'extracted')
  const web       = sources.filter(s => s.source_type === 'web')
  if (!sources.length && !mofs.length) return null

  return (
    <div className="space-y-3">
      {/* Paper sources — extracted + web unified */}
      {sources.length > 0 && (
        <div className="rounded-xl border border-border bg-card px-4 py-3">
          <h3 className="mb-3 flex items-center gap-2 flex-wrap text-xs font-semibold text-slate-200 uppercase tracking-wider">
            <FileText size={12} /> Paper sources
            {extracted.length > 0 && <span className="font-normal normal-case tracking-normal text-teal-400">{extracted.length} extracted</span>}
            {web.filter(s => s.web_source === 'semantic_scholar').length > 0 && <span className="font-normal normal-case tracking-normal text-cyan-400">{web.filter(s => s.web_source === 'semantic_scholar').length} Semantic Scholar</span>}
            {web.filter(s => s.web_source === 'pubmed').length > 0 && <span className="font-normal normal-case tracking-normal text-blue-400">{web.filter(s => s.web_source === 'pubmed').length} PubMed</span>}
            {web.filter(s => s.web_source === 'openalex').length > 0 && <span className="font-normal normal-case tracking-normal text-amber-400">{web.filter(s => s.web_source === 'openalex').length} OpenAlex</span>}
          </h3>
          <div className="space-y-2.5">
            {sources.map((s, i) => <SourceRow key={i} s={s} />)}
          </div>
        </div>
      )}

      {/* DB MOF records */}
      {mofs.length > 0 && (
        <div className="rounded-xl border border-border bg-card px-4 py-3">
          <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-200 uppercase tracking-wider">
            <Database size={12} /> MOF database records used
            <span className="font-normal normal-case tracking-normal text-muted">({mofs.length})</span>
          </h3>
          <div className="space-y-1.5">
            {mofs.map((m: any, i: number) => (
              <div key={i} className="text-xs flex items-baseline gap-2 flex-wrap">
                <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wider ${
                  m.source === 'core_mof' ? 'bg-blue-500/15 text-blue-300' : 'bg-green-500/15 text-green-300'
                }`}>
                  {m.source === 'core_mof' ? 'CoRE' : 'literature'}
                </span>
                <span className="font-medium text-slate-200">{m.name}</span>
                {m.surface_area_m2_g && <span className="text-muted">SA {m.surface_area_m2_g.toFixed(0)} m²/g</span>}
                {m.co2_uptake_value && <span className="text-muted">uptake {m.co2_uptake_value} {m.co2_uptake_unit || ''}</span>}
                {m.henry_law_co2_class && <span className="text-muted">KH: {m.henry_law_co2_class}</span>}
                {(m.measurements?.length ?? 0) > 0 && (
                  <span className="text-muted/60">{m.measurements.length} measurement{m.measurements.length !== 1 ? 's' : ''}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function SourceRow({ s }: { s: AskSource }) {
  const [expanded, setExpanded] = useState(false)
  const href = s.doi ? `https://doi.org/${s.doi}` : s.url

  return (
    <div className="rounded-lg border border-border/40 bg-surface/30 px-3 py-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          {/* Source type badge + title */}
          <div className="flex items-start gap-2">
            {s.citation_number !== undefined && (
              <span className="mt-0.5 flex-shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded bg-slate-600/50 text-slate-200 tabular-nums whitespace-nowrap">
                [{s.citation_number}]
              </span>
            )}
            <span className={`mt-0.5 flex-shrink-0 text-[9px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wider whitespace-nowrap ${
              s.source_type === 'extracted'         ? 'bg-teal-500/15 text-teal-300' :
              s.web_source === 'pubmed'             ? 'bg-blue-500/15 text-blue-300' :
              s.web_source === 'openalex'           ? 'bg-amber-500/15 text-amber-300' :
                                                      'bg-primary/15 text-cyan-300'
            }`}>
              {s.source_type === 'extracted'         ? 'extracted' :
               s.web_source === 'semantic_scholar'   ? 'Semantic Scholar' :
               s.web_source === 'pubmed'             ? 'PubMed' :
               s.web_source === 'openalex'           ? 'OpenAlex' : 'web'}
            </span>
            {href ? (
              <a href={href} target="_blank" rel="noreferrer"
                 className="text-xs font-medium text-slate-200 hover:text-primary hover:underline leading-snug">
                {s.title || 'Untitled'}
              </a>
            ) : (
              <span className="text-xs font-medium text-slate-200 leading-snug">{s.title || 'Untitled'}</span>
            )}
          </div>

          {/* Meta */}
          <div className="flex items-center gap-2 mt-0.5 ml-0 flex-wrap pl-1">
            {s.deepread && (
              <span className="inline-flex items-center gap-0.5 text-[9px] font-semibold px-1.5 py-0.5 rounded bg-teal-500/20 text-teal-300 uppercase tracking-wider">
                <FileText size={8} /> full text read
              </span>
            )}
            {s.authors && s.authors.length > 0 && (
              <span className="text-[10px] text-muted">
                {s.authors.slice(0, 2).join(', ')}{s.authors.length > 2 ? ' et al.' : ''}
              </span>
            )}
            {s.year && <span className="text-[10px] text-muted">· {s.year}</span>}
            {(s.citationCount ?? 0) > 0 && <span className="text-[10px] text-muted">· {s.citationCount} citations</span>}
            {s.doi && (
              <a href={`https://doi.org/${s.doi}`} target="_blank" rel="noreferrer"
                 className="inline-flex items-center gap-0.5 text-[10px] text-primary hover:underline">
                <ExternalLink size={9} /> {s.doi}
              </a>
            )}
            {s.open_access_pdf && (
              <a href={s.open_access_pdf} target="_blank" rel="noreferrer"
                 className="inline-flex items-center gap-0.5 text-[10px] text-teal-400 hover:underline">
                <Download size={9} /> PDF
              </a>
            )}
            {s.source_type === 'extracted' && s.score > 0 && (
              <span className="text-[10px] text-muted/50">· match {s.score.toFixed(3)}</span>
            )}
          </div>
        </div>

        {s.abstract && (
          <button onClick={() => setExpanded(o => !o)}
                  className="text-muted hover:text-slate-300 flex-shrink-0 mt-0.5">
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
        )}
      </div>

      {expanded && s.abstract && (
        <p className="mt-2 ml-1 text-[11px] text-muted leading-relaxed border-t border-border/40 pt-2">
          {s.abstract}
        </p>
      )}
    </div>
  )
}

function TracePanel({ trace, totalMs }: { trace: TraceStep[]; totalMs?: number }) {
  const [open, setOpen] = useState(false)
  if (!trace.length) return null

  const maxMs = Math.max(...trace.map(s => s.ms), 1)

  const STEP_LABEL: Record<string, string> = {
    memory_recall:    'memory recall',
    rag_retrieve:     'RAG retrieve',
    db_query:         'DB query',
    web_search:       'web search',
    deepread:         'full-text fetch',
    rerank:           'embedding rerank',
    query_expansion:  'query expansion',
    llm_answer:       'LLM answer',
    reasoning_agent:  'reasoning agent',
    critic_agent:     'critic agent',
  }

  return (
    <div className="rounded-xl border border-border/40 bg-surface/20 px-4 py-3">
      <button onClick={() => setOpen(o => !o)}
        className="flex w-full items-center justify-between text-xs text-muted hover:text-slate-300 transition-colors">
        <div className="flex items-center gap-2">
          <Activity size={12} className="text-muted/60" />
          <span>Pipeline trace</span>
          {totalMs !== undefined && (
            <span className="text-muted/50">{(totalMs / 1000).toFixed(1)}s total</span>
          )}
        </div>
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>

      {open && (
        <div className="mt-3 space-y-1.5">
          {trace.map((step, i) => {
            const barW = Math.max(Math.round((step.ms / maxMs) * 120), 2)
            const extras = Object.entries(step).filter(([k]) => k !== 'name' && k !== 'ms')
            return (
              <div key={i} className="flex items-center gap-2.5 text-[11px]">
                <span className="w-16 text-right font-mono text-muted/60 flex-shrink-0">
                  {step.ms < 1000 ? `${step.ms}ms` : `${(step.ms / 1000).toFixed(1)}s`}
                </span>
                <div
                  className="h-1 rounded-full bg-primary/40 flex-shrink-0"
                  style={{ width: `${barW}px` }}
                />
                <span className="text-slate-300 font-medium flex-shrink-0">
                  {STEP_LABEL[step.name] ?? step.name}
                </span>
                {extras.length > 0 && (
                  <span className="text-muted/50 truncate">
                    {extras.map(([k, v]) => `${k}=${v}`).join('  ')}
                  </span>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

const EXAMPLE_PROMPTS = [
  'Which MOFs show strong CO2/N2 selectivity under post-combustion conditions?',
  'Find CoRE MOFs with high surface area and strong CO2 Henry class.',
  'MOFs with open metal sites and high water stability are better DAC candidates.',
  'What CO2 uptake values appear in the extracted papers?',
]
