import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Discovery } from './pages/Discovery'
import { Extraction } from './pages/Extraction'
import { DatabasePage } from './pages/Database'
import { AskPage } from './pages/Ask'
import { useState } from 'react'
import type { Paper } from './types'

export default function App() {
  // Shared extraction queue — papers selected on Discovery, processed on Extraction
  const [queue, setQueue] = useState<Paper[]>([])

  const addToQueue = (p: Paper) => {
    setQueue(q => q.find(x => x.paperId === p.paperId) ? q : [...q, p])
  }
  const removeFromQueue = (id: string) => setQueue(q => q.filter(x => x.paperId !== id))
  const clearQueue = () => setQueue([])

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/discover" replace />} />
        <Route path="/discover" element={
          <Discovery queue={queue} onAdd={addToQueue} onRemove={removeFromQueue} />
        } />
        <Route path="/extract" element={
          <Extraction queue={queue} onRemove={removeFromQueue} onClear={clearQueue} />
        } />
        <Route path="/database" element={<DatabasePage />} />
        <Route path="/ask"      element={<AskPage />} />
      </Routes>
    </Layout>
  )
}
