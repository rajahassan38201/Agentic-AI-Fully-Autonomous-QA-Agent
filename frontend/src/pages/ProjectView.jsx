import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getProject, listProjectRuns, replayProjectTest, runProjectTest } from '../api.js'
import RunDetail from '../components/RunDetail.jsx'

const ACTIVE = ['pending', 'running']

export default function ProjectView({ projectId }) {
  const [project, setProject] = useState(null)
  // Only the latest run is kept, so this holds at most one.
  const [runs, setRuns] = useState([])
  const [error, setError] = useState(null)
  const [starting, setStarting] = useState(false)
  const [replaying, setReplaying] = useState(false)
  // Replay options: self-heal on drift (hybrid) vs. strictly deterministic ($0),
  // plus the run-wide ceiling on AI heal steps.
  const [aiHeal, setAiHeal] = useState(true)
  const [healBudget, setHealBudget] = useState(60)

  const load = useCallback(async () => {
    try {
      const [p, r] = await Promise.all([getProject(projectId), listProjectRuns(projectId)])
      setProject(p)
      setRuns(r)
      setError(null)
    } catch (e) {
      setError(String(e.message || e))
    }
  }, [projectId])

  useEffect(() => {
    load()
  }, [load])

  const latestRun = runs[0]
  const running = ACTIVE.includes(latestRun?.status)
  // A replay needs a recorded cassette, which only a completed AI run produces.
  const hasCassette = runs.some(
    (r) => r.status === 'completed' && r.config?.mode !== 'replay'
  )

  // Keep the run in view current while it is in flight, then stop polling.
  useEffect(() => {
    if (!running) return undefined
    const id = setInterval(load, 3000)
    return () => clearInterval(id)
  }, [running, load])

  const handleRun = async () => {
    setStarting(true)
    setError(null)
    try {
      await runProjectTest(projectId)
      await load()
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setStarting(false)
    }
  }

  const handleReplay = async () => {
    setReplaying(true)
    setError(null)
    try {
      await replayProjectTest(projectId, {
        ai_fallback: aiHeal,
        // 0 total budget also disables healing; keep it aligned with the toggle.
        max_heal_total_steps: aiHeal ? Number(healBudget) || 0 : 0,
      })
      await load()
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setReplaying(false)
    }
  }

  if (error && !project) {
    return (
      <div className="page">
        <p className="banner banner-error" role="alert">
          {error}
        </p>
        <Link className="btn btn-quiet" to="/projects">
          Back to projects
        </Link>
      </div>
    )
  }

  if (!project) return <div className="page loading-note">Loading project…</div>

  return (
    <div className="page">
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to="/projects">Projects</Link>
        <span aria-hidden="true">/</span>
        <span aria-current="page">{project.name}</span>
      </nav>

      <header className="page-head">
        <div>
          <h2 className="page-title">{project.name}</h2>
          <p className="page-sub">
            <a href={project.target_url} target="_blank" rel="noreferrer noopener">
              {project.target_url}
            </a>
            <span className="dot-sep" aria-hidden="true" />
            {project.model}
            <span className="dot-sep" aria-hidden="true" />
            max {project.max_steps} steps
          </p>
        </div>

        <div className="page-tools">
          {hasCassette && (
            <div className="replay-opts">
              <label
                className="replay-toggle"
                title="On: drifted steps are self-healed by AI within the budget (hybrid). Off: strictly deterministic replay — drifted steps are skipped and it always costs $0."
              >
                <input
                  type="checkbox"
                  checked={aiHeal}
                  onChange={(e) => setAiHeal(e.target.checked)}
                  disabled={running || replaying}
                />
                AI self-heal
              </label>
              {aiHeal && (
                <label
                  className="replay-budget"
                  title="Run-wide ceiling on AI steps used to repair drifted steps. Caps replay cost."
                >
                  budget
                  <input
                    type="number"
                    min="1"
                    max="2000"
                    step="10"
                    value={healBudget}
                    onChange={(e) => setHealBudget(e.target.value)}
                    disabled={running || replaying}
                  />
                  steps
                </label>
              )}
            </div>
          )}
          <button
            type="button"
            className="btn btn-quiet"
            onClick={handleReplay}
            disabled={running || starting || replaying || !hasCassette}
            title={
              !hasCassette
                ? 'Run a full test first — replay re-uses its recorded steps'
                : running
                ? 'A test is already running for this project'
                : aiHeal
                ? 'Re-run from the recorded cassette; AI self-heals only drifted steps'
                : 'Re-run strictly from the cassette with no AI (always ~$0)'
            }
          >
            {replaying ? 'Starting replay…' : aiHeal ? 'Replay (Hybrid)' : 'Replay (No AI)'}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleRun}
            disabled={running || starting || replaying}
            title={
              running
                ? 'A test is already running for this project'
                : 'Run a test now. This replaces the previous result.'
            }
          >
            {running ? 'Test running…' : starting ? 'Starting…' : 'Run Test'}
          </button>
        </div>
      </header>

      {error && (
        <p className="banner banner-error" role="alert">
          {error}
        </p>
      )}

      {latestRun ? (
        // Remount on a new run so the detail view's polling state starts clean.
        <section className="card detail-card">
          <RunDetail key={latestRun.id} runId={latestRun.id} />
        </section>
      ) : (
        <div className="card table-empty">
          <h3>No tests have run yet</h3>
          <p>Run a test to see findings, activity, and a recording of the session.</p>
          <button type="button" className="btn btn-primary" onClick={handleRun} disabled={starting}>
            {starting ? 'Starting…' : 'Run Test'}
          </button>
        </div>
      )}
    </div>
  )
}
