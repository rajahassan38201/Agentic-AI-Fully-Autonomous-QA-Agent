import { useEffect, useRef, useState } from 'react'
import { getFindings, getRun, getSteps } from '../api.js'
import FindingCard from './FindingCard.jsx'
import StepLog from './StepLog.jsx'

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info']

export default function RunDetail({ runId }) {
  const [run, setRun] = useState(null)
  const [findings, setFindings] = useState([])
  const [steps, setSteps] = useState([])
  const [tab, setTab] = useState('findings')
  const timer = useRef(null)

  useEffect(() => {
    let cancelled = false

    const poll = async () => {
      try {
        const [r, f, s] = await Promise.all([
          getRun(runId),
          getFindings(runId),
          getSteps(runId),
        ])
        if (cancelled) return
        setRun(r)
        setFindings(f)
        setSteps(s)
        const done = r.status === 'completed' || r.status === 'failed'
        if (done && timer.current) {
          clearInterval(timer.current)
          timer.current = null
        }
      } catch (e) {
        console.error(e)
      }
    }

    setRun(null)
    setFindings([])
    setSteps([])
    poll()
    timer.current = setInterval(poll, 2000)
    return () => {
      cancelled = true
      if (timer.current) clearInterval(timer.current)
    }
  }, [runId])

  if (!run) return <div className="empty">Loading…</div>

  const running = run.status === 'pending' || run.status === 'running'
  const counts = SEVERITY_ORDER.map((sev) => ({
    sev,
    n: findings.filter((f) => (f.severity || '').toLowerCase() === sev).length,
  })).filter((c) => c.n > 0)

  const sortedFindings = [...findings].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity)
  )

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <h2>{run.target_url}</h2>
          <div className="detail-sub">
            <span className={`badge badge-${run.status}`}>{run.status}</span>
            {running && <span className="spinner" />}
            <span className="muted">{run.steps_count} steps · {findings.length} findings</span>
          </div>
        </div>
      </div>

      {run.goals && <p className="goals"><strong>Goals:</strong> {run.goals}</p>}

      {counts.length > 0 && (
        <div className="sev-summary">
          {counts.map((c) => (
            <span key={c.sev} className={`sev-tag sev-${c.sev}`}>{c.n} {c.sev}</span>
          ))}
        </div>
      )}

      {run.summary && (
        <div className="card summary">
          <h3>Summary</h3>
          <pre>{run.summary}</pre>
        </div>
      )}

      {run.error && (
        <div className="card error-box">
          <h3>Error</h3>
          <pre>{run.error}</pre>
        </div>
      )}

      <div className="tabs">
        <button className={tab === 'findings' ? 'tab active' : 'tab'} onClick={() => setTab('findings')}>
          Findings ({findings.length})
        </button>
        <button className={tab === 'steps' ? 'tab active' : 'tab'} onClick={() => setTab('steps')}>
          Activity ({steps.length})
        </button>
      </div>

      {tab === 'findings' && (
        <div className="findings">
          {sortedFindings.length === 0 && <p className="muted">No findings recorded yet.</p>}
          {sortedFindings.map((f) => (
            <FindingCard key={f.id} finding={f} />
          ))}
        </div>
      )}

      {tab === 'steps' && <StepLog steps={steps} />}
    </div>
  )
}
