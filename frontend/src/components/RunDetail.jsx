import { useEffect, useRef, useState } from 'react'
import { getFindings, getRun, getSteps, previewUrl, videoUrl, stopRun } from '../api.js'
import FindingCard from './FindingCard.jsx'
import { StopIcon } from './Icons.jsx'
import StatusBadge from './StatusBadge.jsx'
import StepLog from './StepLog.jsx'

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info']

// Session recordings run 20+ minutes and are mostly the agent waiting on page
// loads, so default the replay to 2x. Viewers can still change it in the native
// speed menu — this only sets the starting rate.
const VIDEO_PLAYBACK_RATE = 2

function fmtInt(n) {
  return (Number(n) || 0).toLocaleString()
}

function fmtCost(c) {
  const n = Number(c) || 0
  if (n === 0) return '$0.00'
  if (n < 0.01) return '$' + n.toFixed(4)
  return '$' + n.toFixed(2)
}

export default function RunDetail({ runId }) {
  const [run, setRun] = useState(null)
  const [findings, setFindings] = useState([])
  const [steps, setSteps] = useState([])
  const [tab, setTab] = useState('findings')
  const [previewTick, setPreviewTick] = useState(0)
  const [previewOk, setPreviewOk] = useState(false)
  const [stopping, setStopping] = useState(false)
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
        const done = r.status === 'completed' || r.status === 'failed' || r.status === 'stopped'
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
    setPreviewOk(false)
    setStopping(false)
    poll()
    timer.current = setInterval(poll, 2000)
    return () => {
      cancelled = true
      if (timer.current) clearInterval(timer.current)
    }
  }, [runId])

  // Refresh the live-preview frame on a timer while its tab is open.
  useEffect(() => {
    if (tab !== 'preview') return undefined
    setPreviewTick((t) => t + 1)
    const id = setInterval(() => setPreviewTick((t) => t + 1), 1000)
    return () => clearInterval(id)
  }, [tab, runId])

  if (!run) return <div className="empty">Loading…</div>

  const running = run.status === 'pending' || run.status === 'running'
  const isReplay = run.config?.mode === 'replay'
  const model = (run.config && run.config.model) || 'the configured model'
  const counts = SEVERITY_ORDER.map((sev) => ({
    sev,
    n: findings.filter((f) => (f.severity || '').toLowerCase() === sev).length,
  })).filter((c) => c.n > 0)

  const sortedFindings = [...findings].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity)
  )

  const handleStop = async () => {
    if (stopping) return
    if (!window.confirm('Stop this run now? Progress, activity, and findings so far will be saved.')) {
      return
    }
    setStopping(true)
    try {
      await stopRun(runId)
    } catch (e) {
      console.error(e)
      setStopping(false)
    }
  }

  const tabs = [
    { key: 'findings', label: `Findings (${findings.length})` },
    { key: 'steps', label: `Activity (${steps.length})` },
    { key: 'preview', label: 'Live Preview' },
    { key: 'summary', label: 'Summary' },
    { key: 'cost', label: 'Total Cost' },
  ]

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <h2>{run.target_url}</h2>
          <div className="detail-sub">
            <StatusBadge status={run.status} />
            {isReplay && (
              <span
                className="sev-tag sev-info"
                title="Re-ran a recorded cassette. No AI tokens are spent unless a drifted step needs the model to self-heal."
              >
                Replay · No AI
              </span>
            )}
            {running && <span className="spinner" />}
            <span className="muted">
              {run.steps_count} steps · {findings.length} findings · {fmtCost(run.cost_usd)}
            </span>
          </div>
        </div>
        {running && (
          <button
            type="button"
            className="stop-btn"
            onClick={handleStop}
            disabled={stopping}
            title="Stop this run and save everything so far"
          >
            {stopping ? (
              <>
                <span className="spinner spinner-light" /> Stopping…
              </>
            ) : (
              <>
                <StopIcon /> Stop run
              </>
            )}
          </button>
        )}
      </div>

      {run.goals && <p className="goals"><strong>Goals:</strong> {run.goals}</p>}

      {counts.length > 0 && (
        <div className="sev-summary">
          {counts.map((c) => (
            <span key={c.sev} className={`sev-tag sev-${c.sev}`}>{c.n} {c.sev}</span>
          ))}
        </div>
      )}

      {run.error && (
        <div className="card error-box">
          <h3>Error</h3>
          <pre>{run.error}</pre>
        </div>
      )}

      <div className="tabs">
        {tabs.map((t) => (
          <button
            key={t.key}
            className={tab === t.key ? 'tab active' : 'tab'}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
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

      {tab === 'preview' && (
        <div className="preview">
          <div className="preview-frame">
            {running ? (
              <>
                <img
                  src={previewUrl(runId, previewTick)}
                  alt="Live testing browser"
                  style={{ display: previewOk ? 'block' : 'none' }}
                  onLoad={() => setPreviewOk(true)}
                  onError={() => setPreviewOk(false)}
                />
                {!previewOk && (
                  <div className="preview-empty">
                    <span className="spinner" />
                    <p>Waiting for the browser to start…</p>
                  </div>
                )}
                {previewOk && (
                  <span className="preview-live"><span className="dot" /> Live</span>
                )}
              </>
            ) : run.has_video ? (
              <video
                key={runId}
                className="preview-video"
                src={videoUrl(runId)}
                controls
                preload="metadata"
                // playbackRate is a DOM property, not an attribute, so it has to
                // be assigned on the element. Do it once metadata is in: the
                // browser resets the rate to defaultPlaybackRate while loading,
                // so setting it any earlier gets overwritten.
                onLoadedMetadata={(e) => {
                  e.currentTarget.defaultPlaybackRate = VIDEO_PLAYBACK_RATE
                  e.currentTarget.playbackRate = VIDEO_PLAYBACK_RATE
                }}
              />
            ) : (
              <div className="preview-empty">
                <p>No recorded video is available for this run.</p>
              </div>
            )}
          </div>
          <p className="muted preview-note">
            {running
              ? 'The agent runs a real headless Chromium browser. This preview streams the latest frame after each action so you can watch the test live.'
              : run.has_video
              ? 'Recorded session — replay the entire test end to end without rerunning.'
              : 'This run has no recorded video.'}
          </p>
        </div>
      )}

      {tab === 'summary' && (
        <div className="summary-tab">
          {run.summary ? (
            <div className="card summary">
              <pre>{run.summary}</pre>
            </div>
          ) : (
            <p className="muted">
              {running
                ? 'The final summary will appear here when the run finishes.'
                : 'No summary was produced for this run.'}
            </p>
          )}
        </div>
      )}

      {tab === 'cost' && (
        <div className="cost">
          <div className="cost-hero">
            <div className="cost-label">
              {isReplay ? 'Replay cost (AI-free rerun)' : 'Approximate total cost'}
            </div>
            <div className="cost-amount">{fmtCost(run.cost_usd)}</div>
            <div className="cost-sub">
              {running ? 'accumulating…' : 'final'}
              {isReplay ? ' · replayed recorded steps, no model calls' : ` · ${model}`}
            </div>
            {isReplay && run.cost_saved > 0 && (
              <div className="cost-saved-note">
                Saved {fmtCost(run.cost_saved)} vs. re-running the AI test
              </div>
            )}
          </div>

          <div className="cost-grid">
            <div className="cost-cell">
              <span>Input tokens</span>
              <strong>{fmtInt(run.input_tokens)}</strong>
            </div>
            <div className="cost-cell">
              <span>Output tokens</span>
              <strong>{fmtInt(run.output_tokens)}</strong>
            </div>
            {run.cache_read_tokens > 0 && (
              <div className="cost-cell">
                <span>Cache read</span>
                <strong>{fmtInt(run.cache_read_tokens)}</strong>
              </div>
            )}
            {run.cache_write_tokens > 0 && (
              <div className="cost-cell">
                <span>Cache write</span>
                <strong>{fmtInt(run.cache_write_tokens)}</strong>
              </div>
            )}
            <div className="cost-cell cost-cell-total">
              <span>Total tokens</span>
              <strong>{fmtInt(run.total_tokens)}</strong>
            </div>
          </div>

          <p className="muted">
            Estimated from total token usage at {model} pricing. This is an approximation —
            actual billing may differ.
          </p>
        </div>
      )}
    </div>
  )
}
