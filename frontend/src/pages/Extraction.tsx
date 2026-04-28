import { useState, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Play, Trash2, Upload, CheckCircle, XCircle, Loader2,
         FileText, Zap, AlertTriangle, ChevronDown, ChevronUp, FlaskConical,
         ExternalLink, Download, Atom } from 'lucide-react'
import { api } from '../api'
import type { Paper, ExtractionEvent } from '../types'

interface MofDetail {
  id: number
  name: string
  metal_node?: string
  topology?: string
  has_open_metal_site?: number | null
  functionalization?: string
  surface_area_m2_g?: number
  pore_volume_cm3_g?: number
  pore_limiting_diameter_A?: number
  largest_cavity_diameter_A?: number
  void_fraction?: number
  crystal_density_g_cm3?: number
  water_stability?: string
  thermal_stability_c?: number
  stability_notes?: string
  measurements: {
    id: number
    measurement_type: string
    value?: number
    unit?: string
    temperature_k?: number
    pressure_bar?: number
    selectivity_definition?: string
    application_type?: string
    evidence_quote?: string
    confidence?: number
  }[]
}

interface PaperState {
  paper: Paper
  status: ExtractionEvent['type']
  message?: string
  chars?: number
  method?: string
  mof_count?: number
  measurement_count?: number
  mof_names?: string[]
  paper_db_id?: number
  can_upload?: boolean
  expanded: boolean
  mof_details?: MofDetail[]
  loading_details?: boolean
}

interface Props {
  queue: Paper[]
  onRemove: (id: string) => void
  onClear: () => void
}

const STATUS_CONFIG: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  pending:    { label: 'Pending',    icon: <FileText size={14} />,                             color: 'text-muted'   },
  fetching:   { label: 'Fetching',   icon: <Loader2 size={14} className="animate-spin" />,      color: 'text-info'    },
  extracting: { label: 'Extracting', icon: <Zap size={14} className="animate-pulse-slow" />,    color: 'text-warning' },
  extracted:  { label: 'Extracted',  icon: <CheckCircle size={14} />,                           color: 'text-success' },
  no_mofs:    { label: 'No MOFs',    icon: <AlertTriangle size={14} />,                         color: 'text-warning' },
  failed:     { label: 'Failed',     icon: <XCircle size={14} />,                              color: 'text-danger'  },
  skip:       { label: 'Skipped',    icon: <CheckCircle size={14} />,                           color: 'text-muted'   },
  filtered:   { label: 'Filtered',   icon: <AlertTriangle size={14} />,                         color: 'text-warning' },
}

const SKIP_REASON: Record<string, string> = {
  extracted: 'already extracted',
  no_mofs:   'already processed — no MOFs found',
}

const MEAS_LABEL: Record<string, string> = {
  co2_uptake:       'CO₂ uptake',
  selectivity:      'Selectivity',
  working_capacity: 'Working cap.',
}

function isRateLimit(msg?: string) {
  if (!msg) return false
  const l = msg.toLowerCase()
  return l.includes('429') || l.includes('rate limit') || l.includes('quota') || l.includes('too many')
}

function fmt(v: number | undefined | null, digits = 1) {
  if (v === undefined || v === null) return null
  return Number.isFinite(v) ? v.toFixed(digits) : null
}

export function Extraction({ queue, onRemove, onClear }: Props) {
  const [states, setStates] = useState<Record<string, PaperState>>({})
  const [running, setRunning] = useState(false)
  const [done, setDone] = useState(false)
  const closeRef = useRef<(() => void) | null>(null)

  const updateState = useCallback((paperId: string, update: Partial<PaperState>) => {
    setStates(s => ({ ...s, [paperId]: { ...s[paperId], ...update } }))
  }, [])

  const startExtraction = async () => {
    if (!queue.length || running) return
    setRunning(true)
    setDone(false)

    const init: Record<string, PaperState> = {}
    queue.forEach(p => { init[p.paperId] = { paper: p, status: 'pending', expanded: false } })
    setStates(init)

    try {
      const { job_id } = await api.startExtraction(queue)
      const close = api.streamExtraction(job_id, async (event: ExtractionEvent) => {
        if (event.type === 'done') { setRunning(false); setDone(true); close(); return }
        if (event.type === 'ping') return

        const pid = event.paper
        if (!pid) return
        const paper = queue.find(p =>
          (p.doi && p.doi === pid) || p.title?.startsWith(pid.replace('...', ''))
        )
        if (!paper) return

        const isExtracted = event.type === 'extracted'
        setStates(s => ({
          ...s,
          [paper.paperId]: {
            ...s[paper.paperId],
            paper,
            status: event.type as any,
            message: event.reason || event.status,
            chars: event.chars,
            method: event.method,
            mof_count: event.mof_count,
            measurement_count: event.measurement_count,
            mof_names: event.mof_names,
            paper_db_id: event.paper_db_id,
            can_upload: event.can_upload,
            expanded: isExtracted || event.type === 'failed' || event.type === 'no_mofs',
            loading_details: isExtracted,
          },
        }))

        // Fetch full MOF details after successful extraction
        if (isExtracted && event.paper_db_id) {
          try {
            const { mofs } = await api.getPaperMofs(event.paper_db_id)
            setStates(s => ({
              ...s,
              [paper.paperId]: { ...s[paper.paperId], mof_details: mofs, loading_details: false },
            }))
          } catch {
            setStates(s => ({
              ...s,
              [paper.paperId]: { ...s[paper.paperId], loading_details: false },
            }))
          }
        }
      })
      closeRef.current = close
    } catch (e) {
      setRunning(false)
    }
  }

  const handleUpload = async (paperId: string, paper_db_id: number, file: File) => {
    updateState(paperId, { status: 'extracting', message: 'Processing uploaded PDF...', loading_details: false })
    try {
      const { job_id } = await api.uploadPdf(paper_db_id, file)
      const close = api.streamExtraction(job_id, async (event: ExtractionEvent) => {
        if (event.type === 'done' || event.type === 'extracted' || event.type === 'no_mofs' || event.type === 'error') {
          const isExtracted = event.type === 'extracted'
          updateState(paperId, {
            status: event.type === 'error' ? 'failed' : event.type as any,
            mof_count: event.mof_count,
            measurement_count: event.measurement_count,
            mof_names: event.mof_names,
            message: event.type === 'error' ? (event as any).reason : undefined,
            expanded: true,
            loading_details: isExtracted,
          })
          close()
          if (isExtracted) {
            try {
              const { mofs } = await api.getPaperMofs(paper_db_id)
              updateState(paperId, { mof_details: mofs, loading_details: false })
            } catch {
              updateState(paperId, { loading_details: false })
            }
          }
        }
      })
    } catch (e) {
      updateState(paperId, { status: 'failed', message: 'Upload failed', expanded: true })
    }
  }

  const toggleExpand = (paperId: string) =>
    setStates(s => ({ ...s, [paperId]: { ...s[paperId], expanded: !s[paperId]?.expanded } }))

  const extractedCount = Object.values(states).filter(s => s.status === 'extracted').length
  const failedCount    = Object.values(states).filter(s => s.status === 'failed').length

  return (
    <div className="flex flex-col h-full">
      <header className="px-8 pt-8 pb-6 border-b border-border">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-100 mb-1">Extract</h1>
            <p className="text-sm text-muted">
              Fetch full text via Unpaywall, PMC, EuropePMC, or PDF upload. Extract MOF records with GPT-4o and index into the vector store for RAG.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {done && (
              <div className="text-xs text-muted">{extractedCount} extracted · {failedCount} failed</div>
            )}
            <button onClick={onClear} disabled={running} className="btn-ghost text-xs">
              <Trash2 size={12} /> Clear queue
            </button>
            <button onClick={startExtraction} disabled={!queue.length || running} className="btn-primary">
              {running
                ? <><Loader2 size={14} className="animate-spin" /> Running...</>
                : <><Play size={14} /> Run Pipeline ({queue.length})</>}
            </button>
          </div>
        </div>

        {running && queue.length > 0 && (
          <div className="mt-4 h-1 bg-border rounded-full overflow-hidden">
            <motion.div className="h-full bg-primary"
              animate={{ width: `${(Object.values(states).filter(s =>
                ['extracted','no_mofs','failed','skip','filtered'].includes(s.status as string)
              ).length / queue.length) * 100}%` }}
              transition={{ duration: 0.5 }} />
          </div>
        )}
      </header>

      <div className="flex-1 overflow-auto px-8 py-6">
        {queue.length === 0 && (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <FlaskConical size={48} className="text-border mb-4" />
            <p className="text-muted">No papers queued</p>
            <p className="text-xs text-muted/60 mt-1">Go to Discover to add papers</p>
          </div>
        )}

        <div className="space-y-3">
          {queue.map(paper => {
            const state  = states[paper.paperId]
            const status = state?.status || 'pending'
            const cfg    = STATUS_CONFIG[status] || STATUS_CONFIG.pending
            const canExpand = ['extracted', 'failed', 'no_mofs'].includes(status)

            return (
              <motion.div key={paper.paperId}
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                className="card overflow-hidden">

                {/* ── Header row ── */}
                <div className="p-4 flex items-start gap-3">
                  <div className={`mt-0.5 ${cfg.color}`}>{cfg.icon}</div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-slate-100 leading-snug">{paper.title}</p>

                        {/* Paper links */}
                        <div className="flex items-center gap-3 mt-1 flex-wrap">
                          {paper.doi && (
                            <a href={`https://doi.org/${paper.doi}`} target="_blank" rel="noreferrer"
                               className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
                              <ExternalLink size={10} /> DOI
                            </a>
                          )}
                          {paper.open_access_pdf && (
                            <a href={paper.open_access_pdf} target="_blank" rel="noreferrer"
                               className="inline-flex items-center gap-1 text-xs text-teal-400 hover:underline">
                              <Download size={10} /> Download PDF
                            </a>
                          )}
                          {paper.url && !paper.open_access_pdf && (
                            <a href={paper.url} target="_blank" rel="noreferrer"
                               className="inline-flex items-center gap-1 text-xs text-muted hover:text-slate-300 hover:underline">
                              <ExternalLink size={10} /> View paper
                            </a>
                          )}
                        </div>

                        {/* Status line */}
                        <div className="flex items-center gap-2 mt-1 flex-wrap">
                          <span className={`text-xs ${cfg.color} font-medium`}>{cfg.label}</span>
                          {status === 'skip' && state?.message && (
                            <span className="text-xs text-muted">· {SKIP_REASON[state.message] ?? state.message}</span>
                          )}
                          {state?.chars && (
                            <span className="text-xs text-muted">
                              · {(state.chars / 1000).toFixed(0)}k chars via {state.method}
                            </span>
                          )}
                          {state?.mof_count !== undefined && status === 'extracted' && (
                            <span className="text-xs text-success font-medium">
                              · {state.mof_count} MOF{state.mof_count !== 1 ? 's' : ''}
                              {state.measurement_count ? `, ${state.measurement_count} measurements` : ''}
                            </span>
                          )}
                          {state?.message && status === 'failed' && (
                            <span className={`text-xs font-medium ${isRateLimit(state.message) ? 'text-warning' : 'text-danger'}`}>
                              · {isRateLimit(state.message) ? 'Rate limit hit' : state.message}
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="flex items-center gap-2 flex-shrink-0">
                        {!running && status === 'pending' && (
                          <button onClick={() => onRemove(paper.paperId)} className="btn-ghost text-xs py-1 px-2">
                            <Trash2 size={11} />
                          </button>
                        )}
                        {canExpand && (
                          <button onClick={() => toggleExpand(paper.paperId)} className="btn-ghost text-xs py-1 px-2">
                            {state?.expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                          </button>
                        )}
                      </div>
                    </div>

                    {(status === 'fetching' || status === 'extracting') && (
                      <div className="mt-2 h-0.5 bg-border rounded overflow-hidden">
                        <motion.div className={`h-full ${status === 'fetching' ? 'bg-info' : 'bg-warning'}`}
                          animate={{ x: ['0%', '100%', '0%'] }}
                          transition={{ duration: 1.5, repeat: Infinity, ease: 'easeInOut' }}
                          style={{ width: '40%' }} />
                      </div>
                    )}
                  </div>
                </div>

                {/* ── Expanded detail panel ── */}
                <AnimatePresence>
                  {state?.expanded && (
                    <motion.div initial={{ height: 0 }} animate={{ height: 'auto' }} exit={{ height: 0 }}
                      className="overflow-hidden border-t border-border">

                      {/* Extracted: full MOF details */}
                      {status === 'extracted' && (
                        <div className="px-4 py-4">
                          {state.loading_details ? (
                            <div className="flex items-center gap-2 text-xs text-muted py-2">
                              <Loader2 size={12} className="animate-spin" /> Loading extracted data...
                            </div>
                          ) : state.mof_details && state.mof_details.length > 0 ? (
                            <div className="space-y-4">
                              {state.mof_details.map(mof => (
                                <MofDetailCard key={mof.id} mof={mof} />
                              ))}
                            </div>
                          ) : (
                            /* Fallback: just show names if DB fetch failed */
                            (state.mof_names?.length ?? 0) > 0 && (
                              <div className="flex flex-wrap gap-1.5">
                                {state.mof_names!.map((name, i) => (
                                  <span key={i} className="rounded-md bg-success/10 border border-success/25 px-2 py-0.5 text-xs text-success">
                                    {name}
                                  </span>
                                ))}
                              </div>
                            )
                          )}
                        </div>
                      )}

                      {/* Failed: error + upload */}
                      {status === 'failed' && (
                        <div className="px-4 py-3 space-y-3">
                          {state?.message && (
                            <div className={`rounded-lg px-3 py-2 text-xs ${
                              isRateLimit(state.message)
                                ? 'bg-warning/10 border border-warning/25 text-warning'
                                : 'bg-danger/10 border border-danger/25 text-danger'
                            }`}>
                              {isRateLimit(state.message) ? (
                                <>
                                  <p className="font-semibold mb-0.5">Rate limit reached</p>
                                  <p className="opacity-80">Wait a minute and retry, or upload the PDF manually below.</p>
                                </>
                              ) : (
                                <>
                                  <p className="font-semibold mb-0.5">Fetch failed</p>
                                  <p className="opacity-80">{state.message}</p>
                                  <p className="mt-1 opacity-70">Download from the link above and upload below.</p>
                                </>
                              )}
                            </div>
                          )}
                          {state?.can_upload && state?.paper_db_id && (
                            <UploadZone onFile={f => handleUpload(paper.paperId, state.paper_db_id!, f)} />
                          )}
                        </div>
                      )}

                      {/* No MOFs: explanation + upload */}
                      {status === 'no_mofs' && (
                        <div className="px-4 py-3 space-y-3">
                          <div className="rounded-lg bg-warning/10 border border-warning/25 px-3 py-2 text-xs text-warning">
                            <p className="font-semibold mb-1">No MOF records extracted</p>
                            <ul className="space-y-0.5 list-disc list-inside opacity-80">
                              <li>Paper may discuss MOFs qualitatively without performance numbers</li>
                              <li>Numbers may be in image-only tables the LLM could not read</li>
                              <li>Paper may focus on non-CO₂ gases (VOC, H₂, CH₄)</li>
                            </ul>
                          </div>
                          {state?.can_upload && state?.paper_db_id && (
                            <UploadZone onFile={f => handleUpload(paper.paperId, state.paper_db_id!, f)} />
                          )}
                        </div>
                      )}
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── MOF detail card ────────────────────────────────────────────────────────────

function MofDetailCard({ mof }: { mof: MofDetail }) {
  const [open, setOpen] = useState(true)

  const structural = [
    { label: 'Surface area',  value: fmt(mof.surface_area_m2_g),        unit: 'm²/g' },
    { label: 'Pore volume',   value: fmt(mof.pore_volume_cm3_g, 3),     unit: 'cm³/g' },
    { label: 'PLD',           value: fmt(mof.pore_limiting_diameter_A), unit: 'Å' },
    { label: 'LCD',           value: fmt(mof.largest_cavity_diameter_A),unit: 'Å' },
    { label: 'Void fraction', value: fmt(mof.void_fraction, 3),         unit: '' },
    { label: 'Density',       value: fmt(mof.crystal_density_g_cm3, 3), unit: 'g/cm³' },
  ].filter(f => f.value !== null)

  return (
    <div className="rounded-lg border border-border bg-surface/60 overflow-hidden">
      {/* MOF header */}
      <button onClick={() => setOpen(o => !o)}
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-surface transition-colors">
        <div className="flex items-center gap-2">
          <Atom size={14} className="text-teal-400 flex-shrink-0" />
          <span className="text-sm font-semibold text-slate-100">{mof.name}</span>
          {mof.metal_node && <span className="text-xs text-muted">· {mof.metal_node}</span>}
          {mof.topology   && <span className="text-xs text-muted">· {mof.topology}</span>}
          {mof.has_open_metal_site != null && (
            <span className={`text-[10px] font-medium ${mof.has_open_metal_site ? 'text-teal-400' : 'text-muted'}`}>
              {mof.has_open_metal_site ? '· OMS ✓' : '· no OMS'}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-muted">{mof.measurements.length} measurement{mof.measurements.length !== 1 ? 's' : ''}</span>
          {open ? <ChevronUp size={13} className="text-muted" /> : <ChevronDown size={13} className="text-muted" />}
        </div>
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-4">
          {/* Structural fields */}
          {structural.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted mb-2 font-semibold">Structure</p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-1">
                {structural.map(f => (
                  <div key={f.label} className="flex items-baseline gap-1 text-xs">
                    <span className="text-muted min-w-[90px]">{f.label}</span>
                    <span className="text-slate-200 font-medium">{f.value}</span>
                    {f.unit && <span className="text-muted">{f.unit}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Stability */}
          {(mof.water_stability || mof.thermal_stability_c != null || mof.stability_notes) && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted mb-2 font-semibold">Stability</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 text-xs">
                {mof.water_stability && (
                  <div className="flex gap-1">
                    <span className="text-muted min-w-[90px]">Water</span>
                    <span className="text-slate-200">{mof.water_stability}</span>
                  </div>
                )}
                {mof.thermal_stability_c != null && (
                  <div className="flex gap-1">
                    <span className="text-muted min-w-[90px]">Thermal</span>
                    <span className="text-slate-200">{mof.thermal_stability_c} °C</span>
                  </div>
                )}
                {mof.stability_notes && (
                  <div className="flex gap-1 sm:col-span-2">
                    <span className="text-muted min-w-[90px]">Notes</span>
                    <span className="text-slate-300">{mof.stability_notes}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Measurements table */}
          {mof.measurements.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted mb-2 font-semibold">Measurements</p>
              <div className="overflow-hidden rounded-lg border border-border/60">
                <table className="w-full text-xs">
                  <thead className="border-b border-border/60 bg-surface text-[10px] uppercase tracking-wider text-muted">
                    <tr>
                      <th className="px-3 py-2 text-left">Type</th>
                      <th className="px-3 py-2 text-left">Value</th>
                      <th className="px-3 py-2 text-left">Conditions</th>
                      <th className="px-3 py-2 text-left">Application</th>
                      <th className="px-3 py-2 text-left">Confidence</th>
                      <th className="px-3 py-2 text-left">Evidence</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/40">
                    {mof.measurements.map((ms, i) => (
                      <tr key={i} className="bg-card/20 hover:bg-card/50">
                        <td className="px-3 py-2 text-muted whitespace-nowrap">
                          {MEAS_LABEL[ms.measurement_type] ?? ms.measurement_type}
                        </td>
                        <td className="px-3 py-2 font-medium text-slate-200 whitespace-nowrap">
                          {ms.value ?? '—'}
                          {ms.unit && <span className="ml-1 text-muted">{ms.unit}</span>}
                          {ms.selectivity_definition && (
                            <span className="ml-1 text-muted">({ms.selectivity_definition})</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-muted whitespace-nowrap">
                          {[
                            ms.temperature_k  ? `${ms.temperature_k} K`   : '',
                            ms.pressure_bar   ? `${ms.pressure_bar} bar`  : '',
                          ].filter(Boolean).join(' / ') || '—'}
                        </td>
                        <td className="px-3 py-2 text-muted capitalize whitespace-nowrap">
                          {ms.application_type?.replace('_', ' ') || '—'}
                        </td>
                        <td className="px-3 py-2">
                          {ms.confidence != null ? <ConfBar value={ms.confidence} /> : '—'}
                        </td>
                        <td className="max-w-[260px] px-3 py-2 text-muted">
                          <span className="line-clamp-2">{ms.evidence_quote || '—'}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ConfBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = value >= 0.8 ? 'bg-success' : value >= 0.6 ? 'bg-warning' : 'bg-danger'
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1.5 w-14 rounded-full bg-border overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-muted">{pct}%</span>
    </div>
  )
}

function UploadZone({ onFile }: { onFile: (f: File) => void }) {
  const [drag, setDrag] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const handle = (files: FileList | null) => { if (files?.[0]) onFile(files[0]) }

  return (
    <div>
      <p className="text-xs text-muted mb-2">Upload the PDF manually to retry extraction:</p>
      <div
        onDragOver={e => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); handle(e.dataTransfer.files) }}
        onClick={() => inputRef.current?.click()}
        className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-all ${
          drag ? 'border-primary bg-primary/10' : 'border-border hover:border-muted'
        }`}>
        <Upload size={20} className="mx-auto mb-2 text-muted" />
        <p className="text-xs text-muted">Drop PDF here or click to browse</p>
        <input ref={inputRef} type="file" accept=".pdf" className="hidden"
               onChange={e => handle(e.target.files)} />
      </div>
    </div>
  )
}
