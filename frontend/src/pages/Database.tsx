import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Database, Search, SlidersHorizontal } from 'lucide-react'
import { api } from '../api'
import type { DBStats, MOFRecord, Measurement } from '../types'

const SOURCE_LABEL: Record<string, string> = {
  core_mof:   'CoRE MOF',
  literature: 'Literature',
}

const MEAS_TYPE_LABEL: Record<string, string> = {
  co2_uptake:       'CO₂ uptake',
  selectivity:      'Selectivity',
  working_capacity: 'Working cap.',
}

export function DatabasePage() {
  const [source,          setSource]          = useState('')
  const [search,          setSearch]          = useState('')
  const [metal,           setMetal]           = useState('')
  const [applicationType, setApplicationType] = useState('')
  const [minSurfaceArea,  setMinSurfaceArea]  = useState('')
  const [minCo2Uptake,    setMinCo2Uptake]    = useState('')
  const [sortBy,          setSortBy]          = useState('surface_area_m2_g')

  const params = useMemo(() => ({
    source, search, metal,
    application_type: applicationType,
    min_surface_area: minSurfaceArea || undefined,
    min_co2_uptake:   minCo2Uptake   || undefined,
    sort_by: sortBy, sort_desc: true, limit: 100,
  }), [source, search, metal, applicationType, minSurfaceArea, minCo2Uptake, sortBy])

  const stats = useQuery<DBStats>({ queryKey: ['stats'],        queryFn: api.getStats })
  const mofs  = useQuery({          queryKey: ['mofs', params], queryFn: () => api.getMofs(params) })
  const rows: MOFRecord[] = mofs.data?.mofs ?? []

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-border px-8 pb-6 pt-8">
        <div className="flex items-start justify-between gap-6">
          <div>
            <h1 className="text-2xl font-semibold text-slate-100">Database</h1>
            <p className="mt-1 text-sm text-muted">
              Unified view of CoRE MOF simulation records (structural + Henry-law CO₂ class) and literature-extracted records (uptake, selectivity, working capacity). Expand any row to see all measured conditions.
            </p>
          </div>
          <div className="hidden grid-cols-4 gap-2 lg:grid">
            <Stat label="Total MOFs" value={stats.data?.total_mofs ?? 0} />
            <Stat label="CoRE MOF"   value={stats.data?.core_mof   ?? 0} />
            <Stat label="Literature" value={stats.data?.literature  ?? 0} />
            <Stat label="Papers"     value={stats.data?.papers_total ?? 0} />
          </div>
        </div>
      </header>

      {/* Filters */}
      <div className="border-b border-border bg-surface/40 px-8 py-4">
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-7">
          <div className="relative lg:col-span-2">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input className="input pl-9" value={search} onChange={e => setSearch(e.target.value)}
                   placeholder="Search name, metal, paper title" />
          </div>
          <select className="input" value={source} onChange={e => setSource(e.target.value)}>
            <option value="">All sources</option>
            <option value="core_mof">CoRE MOF</option>
            <option value="literature">Literature</option>
          </select>
          <input className="input" value={metal} onChange={e => setMetal(e.target.value)}
                 placeholder="Metal node" />
          <select className="input" value={applicationType} onChange={e => setApplicationType(e.target.value)}>
            <option value="">All applications</option>
            <option value="DAC">DAC</option>
            <option value="post_combustion">Post-combustion</option>
            <option value="pre_combustion">Pre-combustion</option>
          </select>
          <input className="input" type="number" value={minSurfaceArea}
                 onChange={e => setMinSurfaceArea(e.target.value)} placeholder="Min SA (m²/g)" />
          <input className="input" type="number" value={minCo2Uptake}
                 onChange={e => setMinCo2Uptake(e.target.value)} placeholder="Min CO₂ uptake" />
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-muted">
          <SlidersHorizontal size={13} />
          <span>Sort</span>
          <select className="input max-w-[220px] py-1 text-xs" value={sortBy}
                  onChange={e => setSortBy(e.target.value)}>
            <option value="surface_area_m2_g">Surface area</option>
            <option value="co2_uptake_value">CO₂ uptake (best)</option>
            <option value="selectivity_value">Selectivity (best)</option>
            <option value="thermal_stability_c">Thermal stability</option>
            <option value="water_stability_score">Water stability</option>
          </select>
          <span className="ml-auto">{mofs.data?.total ?? 0} matching records</span>
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto px-8 py-6">
        {mofs.isLoading && (
          <div className="py-8 text-center text-sm text-muted">Loading database...</div>
        )}

        {!mofs.isLoading && rows.length === 0 && (
          <div className="flex flex-col items-center justify-center py-24 text-center text-muted">
            <Database size={44} className="mb-4 text-border" />
            <p className="text-sm">No MOF records match the current filters.</p>
            {stats.data?.total_mofs === 0 && (
              <p className="mt-2 text-xs text-muted/60">
                Import CoRE MOF data to get started — see the README.
              </p>
            )}
          </div>
        )}

        {rows.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-border">
            <table className="w-full min-w-[980px] text-left text-sm">
              <thead className="border-b border-border bg-surface text-[11px] uppercase tracking-wider text-muted">
                <tr>
                  <th className="w-6 px-3 py-3" />
                  <th className="px-4 py-3">MOF</th>
                  <th className="px-4 py-3">Source</th>
                  <th className="px-4 py-3">Metal / Topo</th>
                  <th className="px-4 py-3">Geometry</th>
                  <th className="px-4 py-3">Best CO₂ performance</th>
                  <th className="px-4 py-3">Stability</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map(row => <MofRow key={row.id} row={row} />)}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function MofRow({ row }: { row: MOFRecord }) {
  const [open, setOpen] = useState(false)
  const hasExpand = row.source === 'literature' && (row.measurements?.length ?? 0) > 0

  return (
    <>
      <tr className={`bg-card/40 align-top transition-colors hover:bg-card ${open ? 'bg-card' : ''}`}>
        {/* Expand toggle */}
        <td className="px-3 py-3">
          {hasExpand
            ? <button onClick={() => setOpen(o => !o)} className="text-muted hover:text-slate-200 transition-colors">
                {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>
            : <span className="w-4 block" />}
        </td>

        {/* Name */}
        <td className="px-4 py-3">
          <div className="font-medium text-slate-100">{row.name}</div>
          <div className="mt-0.5 text-xs text-muted">
            {row.refcode || row.coreid || row.paper_doi || ''}
          </div>
          {row.source === 'literature' && row.measurements && row.measurements.length > 0 && (
            <div className="mt-1 text-[10px] text-muted/60">
              {row.measurements.length} condition{row.measurements.length !== 1 ? 's' : ''}
            </div>
          )}
        </td>

        {/* Source */}
        <td className="px-4 py-3">
          <span className={row.source === 'core_mof' ? 'badge-blue' : 'badge-green'}>
            {SOURCE_LABEL[row.source] || row.source}
          </span>
          {row.source_dataset && (
            <div className="mt-1 text-xs text-muted">{row.source_dataset}</div>
          )}
        </td>

        {/* Metal / Topology */}
        <td className="px-4 py-3 text-xs text-slate-300">
          <div>{row.metal_node || '—'}</div>
          {row.topology && <div className="mt-0.5 text-muted">{row.topology}</div>}
          {row.has_open_metal_site != null && (
            <div className={`mt-0.5 text-[10px] ${row.has_open_metal_site ? 'text-teal-400' : 'text-muted'}`}>
              {row.has_open_metal_site ? 'OMS ✓' : 'no OMS'}
            </div>
          )}
        </td>

        {/* Geometry */}
        <td className="px-4 py-3 text-xs text-slate-300">
          <Value label="SA"  value={fmt(row.surface_area_m2_g)}       unit="m²/g" />
          <Value label="PLD" value={fmt(row.pore_limiting_diameter_A)} unit="Å"    />
          <Value label="VF"  value={fmt(row.void_fraction, 2)}                      />
        </td>

        {/* Best CO2 performance */}
        <td className="px-4 py-3 text-xs text-slate-300">
          {row.source === 'core_mof'
            ? <Value label="KH class" value={row.henry_law_co2_class || '—'} />
            : <>
                <Value label="Uptake" value={fmt(row.co2_uptake_value)}
                       unit={row.co2_uptake_unit || ''} />
                {(row.temperature_k || row.pressure_bar) && (
                  <Value label="T/P" value={[
                    row.temperature_k ? `${fmt(row.temperature_k, 0)}K` : '',
                    row.pressure_bar  ? `${fmt(row.pressure_bar, 2)}bar` : '',
                  ].filter(Boolean).join(' / ')} />
                )}
                <Value label="Sel" value={fmt(row.selectivity_value)}
                       unit={row.selectivity_definition || ''} />
              </>}
        </td>

        {/* Stability */}
        <td className="px-4 py-3 text-xs text-slate-300">
          <Value label="Water"   value={row.water_stability || fmt(row.water_stability_score, 2)} />
          <Value label="Solvent" value={fmt(row.solvent_stability_score, 2)} />
          <Value label="Thermal" value={fmt(row.thermal_stability_c, 0)} unit="°C" />
        </td>
      </tr>

      {/* Measurements sub-rows */}
      {open && hasExpand && (
        <tr className="bg-surface/60">
          <td />
          <td colSpan={6} className="px-4 pb-4 pt-2">
            <p className="mb-2 text-[10px] uppercase tracking-wider text-muted">
              All measured conditions — {row.paper_title || row.paper_doi || 'literature'}
            </p>
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
                  {row.measurements!.map((ms, i) => (
                    <MeasurementRow key={i} ms={ms} />
                  ))}
                </tbody>
              </table>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

function MeasurementRow({ ms }: { ms: Measurement }) {
  return (
    <tr className="bg-card/20 hover:bg-card/50">
      <td className="px-3 py-2 text-muted">
        {MEAS_TYPE_LABEL[ms.measurement_type] || ms.measurement_type}
      </td>
      <td className="px-3 py-2 font-medium text-slate-200">
        {ms.value != null ? ms.value : '—'}
        {ms.unit ? <span className="ml-1 text-muted">{ms.unit}</span> : null}
        {ms.selectivity_definition
          ? <span className="ml-1 text-muted">({ms.selectivity_definition})</span>
          : null}
      </td>
      <td className="px-3 py-2 text-muted">
        {[
          ms.temperature_k  ? `${ms.temperature_k}K`   : '',
          ms.pressure_bar   ? `${ms.pressure_bar}bar`  : '',
        ].filter(Boolean).join(' / ') || '—'}
      </td>
      <td className="px-3 py-2 text-muted capitalize">
        {ms.application_type?.replace('_', ' ') || '—'}
      </td>
      <td className="px-3 py-2">
        {ms.confidence != null
          ? <ConfBar value={ms.confidence} />
          : '—'}
      </td>
      <td className="max-w-[280px] px-3 py-2 text-muted">
        <span className="line-clamp-2">{ms.evidence_quote || '—'}</span>
      </td>
    </tr>
  )
}

function ConfBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = value >= 0.8 ? 'bg-success' : value >= 0.6 ? 'bg-warning' : 'bg-danger'
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1.5 w-16 rounded-full bg-border overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-muted">{pct}%</span>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="min-w-[92px] rounded-lg border border-border bg-surface px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-0.5 text-lg font-semibold text-slate-100">{value.toLocaleString()}</div>
    </div>
  )
}

function Value({ label, value, unit }: { label: string; value?: string; unit?: string }) {
  return (
    <div className="mb-1 flex gap-1">
      <span className="min-w-[54px] text-muted">{label}</span>
      <span>{value || '—'}</span>
      {unit && value && value !== '—' && <span className="text-muted">{unit}</span>}
    </div>
  )
}

function fmt(value: number | string | undefined | null, digits = 1) {
  if (value === undefined || value === null || value === '') return '—'
  if (typeof value === 'string') return value
  return Number.isFinite(value) ? value.toFixed(digits) : '—'
}
