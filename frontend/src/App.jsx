import { useCallback, useEffect, useState } from 'react'
import { listRuns, deleteRun } from './api.js'
import NewRunForm from './components/NewRunForm.jsx'
import RunList from './components/RunList.jsx'
import RunDetail from './components/RunDetail.jsx'

export default function App() {
  const [runs, setRuns] = useState([])
  const [selectedId, setSelectedId] = useState(null)

  const refreshRuns = useCallback(async () => {
    try {
      setRuns(await listRuns())
    } catch (e) {
      console.error(e)
    }
  }, [])

  useEffect(() => {
    refreshRuns()
    const t = setInterval(refreshRuns, 3000)
    return () => clearInterval(t)
  }, [refreshRuns])

  const handleCreated = (run) => {
    setSelectedId(run.id)
    refreshRuns()
  }

  const handleDelete = useCallback(async (id) => {
    // Optimistically drop it from the list; clear the detail pane if it was open.
    setRuns((prev) => prev.filter((r) => r.id !== id))
    setSelectedId((cur) => (cur === id ? null : cur))
    try {
      await deleteRun(id)
    } catch (e) {
      console.error(e)
    } finally {
      refreshRuns()
    }
  }, [refreshRuns])

  return (
    <div className="app">
      <div className="bg-layer" aria-hidden="true">
        <span className="blob blob-1" />
        <span className="blob blob-2" />
        <span className="blob blob-3" />
      </div>

      <header className="topbar">
        <div className="brand">
          <span className="brand-logo">🧪</span>
          <span className="brand-name">Agentic QA</span>
        </div>
        <div className="topbar-spacer" />
        <div className="topbar-pill">
          <span className="dot" />
          Live
        </div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <NewRunForm onCreated={handleCreated} />
          <RunList runs={runs} selectedId={selectedId} onSelect={setSelectedId} onDelete={handleDelete} />
        </aside>

        <main className="content">
          {selectedId ? (
            <RunDetail runId={selectedId} />
          ) : (
            <div className="empty">
              <div className="empty-icon">🚀</div>
              <h2>Start a test run</h2>
              <p>
                Enter a URL on the left and let the agent explore, click, and probe it for you.
                Select a run to watch live progress and findings stream in.
              </p>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
