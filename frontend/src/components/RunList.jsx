function statusClass(status) {
  return `badge badge-${status}`
}

function hostname(url) {
  try {
    return new URL(url).hostname
  } catch {
    return url
  }
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 6h18" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6M14 11v6" />
    </svg>
  )
}

export default function RunList({ runs, selectedId, onSelect, onDelete }) {
  const handleDelete = (e, run) => {
    e.stopPropagation()
    const label = hostname(run.target_url)
    if (window.confirm(`Delete this run for ${label}? This permanently removes it and all its findings.`)) {
      onDelete(run.id)
    }
  }

  return (
    <div className="card">
      <h3>Recent runs</h3>
      {runs.length === 0 && <p className="muted">No runs yet.</p>}
      <ul className="runlist">
        {runs.map((r) => (
          <li
            key={r.id}
            className={r.id === selectedId ? 'runitem active' : 'runitem'}
            onClick={() => onSelect(r.id)}
          >
            <div className="runitem-main">
              <div className="runitem-top">
                <span className="runitem-url">{hostname(r.target_url)}</span>
                <span className={statusClass(r.status)}>{r.status}</span>
              </div>
              <div className="runitem-meta">
                {r.steps_count} steps · {r.findings_count} findings
              </div>
            </div>
            <button
              type="button"
              className="runitem-delete"
              title="Delete run"
              aria-label={`Delete run for ${hostname(r.target_url)}`}
              onClick={(e) => handleDelete(e, r)}
            >
              <TrashIcon />
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
