const BASE = '/api'

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

async function get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v))
    })
  }
  const r = await fetch(url.toString())
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export const api = {
  searchPapers: (body: {
    query: string
    limit: number
    year?: number
    date_from?: string
    date_to?: string
    sort_by: string
    sources: string[]
  }) => post<{ papers: any[]; count: number }>('/papers/search', body),

  assessPapers: (papers: any[]) =>
    post<{ assessments: any[] }>('/papers/assess', { papers }),

  startExtraction: (papers: any[]) =>
    post<{ job_id: string }>('/papers/extract', { papers, skip_already_done: true }),

  getPapers: (limit = 200) => get<{ papers: any[] }>('/papers', { limit }),

  getMofs: (params: Record<string, any>) => get<{ mofs: any[]; total: number }>('/mofs', params),

  getMofMeasurements: (mofId: number) =>
    get<{ measurements: any[] }>(`/mofs/${mofId}/measurements`),

  getPaperMofs: (paperId: number) =>
    get<{ mofs: any[] }>(`/papers/${paperId}/mofs`),

  getStats: () => get<any>('/mofs/stats'),

  ask: (query: string, mode: 'auto' | 'question' | 'hypothesis' | 'chitchat', history: { role: string; content: string }[] = [], deepreadN = 2) =>
    post<any>('/ask', { query, mode, history, deepread_n: deepreadN }),

  uploadPdf: async (paper_db_id: number, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    const r = await fetch(`${BASE}/papers/${paper_db_id}/upload`, { method: 'POST', body: fd })
    if (!r.ok) throw new Error(await r.text())
    return r.json() as Promise<{ job_id: string; message: string }>
  },

  streamExtraction: (jobId: string, onEvent: (e: any) => void): () => void => {
    const es = new EventSource(`${BASE}/papers/extract/stream/${jobId}`)
    es.onmessage = (e) => {
      try { onEvent(JSON.parse(e.data)) } catch {}
    }
    es.onerror = () => es.close()
    return () => es.close()
  },
}
