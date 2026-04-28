export interface Paper {
  paperId: string
  title: string
  authors: string[]
  year: number | null
  abstract: string
  url: string
  doi: string
  pmcid: string
  open_access_pdf: string
  citationCount: number
  source: string
  publicationDate: string
}

export type ExtractionStatus =
  | 'pending'
  | 'skip'
  | 'filtered'
  | 'fetching'
  | 'extracting'
  | 'extracted'
  | 'no_mofs'
  | 'failed'

export interface ExtractionEvent {
  type: ExtractionStatus | 'done' | 'ping' | 'error'
  paper?: string
  title?: string
  status?: string
  reason?: string
  chars?: number
  method?: string
  mof_count?: number
  measurement_count?: number
  mof_names?: string[]
  paper_db_id?: number
  can_upload?: boolean
}

export interface PaperRecord {
  id: number
  title: string
  year: number | null
  doi: string
  source: string
  status: string
  failure_reason: string
  fulltext_chars: number | null
  fulltext_method: string | null
  citation_count: number | null
  publication_date: string
  abstract: string
  created_at: string
}

export interface FullTextAssessment {
  paper_db_id: number
  paperId: string
  title: string
  can_extract: boolean
  quality: 'full_text' | 'partial' | 'too_short' | 'missing' | 'parse_error'
  chars: number
  method: string
  reason: string
  message?: string
}

export interface MOFRecord {
  id: number
  source: 'core_mof' | 'literature'
  source_dataset?: string
  name: string
  refcode?: string
  coreid?: string
  metal_node?: string
  functionalization?: string
  topology?: string
  surface_area_m2_g?: number
  pore_volume_cm3_g?: number
  pore_limiting_diameter_A?: number
  largest_cavity_diameter_A?: number
  void_fraction?: number
  water_stability?: string
  water_stability_score?: number
  solvent_stability_score?: number
  thermal_stability_c?: number
  has_open_metal_site?: number
  co2_uptake_value?: number
  co2_uptake_unit?: string
  temperature_k?: number
  pressure_bar?: number
  selectivity_value?: number
  selectivity_definition?: string
  working_capacity_mmol_g?: number
  application_type?: string
  henry_law_co2_class?: string
  evidence_quote?: string
  confidence?: number
  paper_doi?: string
  paper_title?: string
  measurements?: Measurement[]
}

export type Intent = 'hypothesis' | 'question' | 'chitchat'
export type HypothesisStatus = 'supported' | 'partially_supported' | 'not_supported' | 'insufficient_data' | 'error'

export interface Measurement {
  id: number
  mof_id: number
  measurement_type: 'co2_uptake' | 'selectivity' | 'working_capacity'
  value?: number
  unit?: string
  temperature_k?: number
  pressure_bar?: number
  selectivity_definition?: string
  application_type?: string
  evidence_quote?: string
  confidence?: number
  paper_doi?: string
  paper_title?: string
}

export interface AskSource {
  title: string
  doi?: string
  url?: string
  open_access_pdf?: string
  score: number
  source_type: 'extracted' | 'web'
  web_source?: string
  abstract?: string
  year?: number
  authors?: string[]
  citationCount?: number
  citation_number?: number
  deepread?: boolean
}

export interface TraceStep {
  name: string
  ms: number
  [key: string]: unknown
}

export interface AskResponse {
  intent: Intent
  // Q&A + chitchat
  answer?: string
  source_mix?: { paper_chunks: number; database_records: number; uses_rag: boolean; uses_mof_database: boolean }
  // Hypothesis
  status?: HypothesisStatus
  summary?: string
  reasons_for?: string[]
  reasons_against?: string[]
  data_gaps?: string[]
  confidence?: number
  critic_challenges?: string[]
  overlooked_evidence?: string[]
  // Shared
  sources: AskSource[]
  db_mofs: any[]
  // Pipeline trace
  trace?: TraceStep[]
  trace_total_ms?: number
}

export interface DBStats {
  total_mofs: number
  core_mof: number
  literature: number
  papers_total: number
  papers_extracted: number
  application_types: Record<string, number>
}
