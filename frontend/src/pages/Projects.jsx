import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { deleteProject, listProjects, runProjectTest } from '../api.js'
import ConfirmDialog from '../components/ConfirmDialog.jsx'
import { EyeIcon, PencilIcon, PlusIcon, SearchIcon, TrashIcon } from '../components/Icons.jsx'
import ProjectModal from '../components/ProjectModal.jsx'
import StatusBadge from '../components/StatusBadge.jsx'

const FILTERS = [
  { value: 'all', label: 'All Statuses' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'running', label: 'Running' },
  { value: 'none', label: 'Not Running' },
]

const ACTIVE = ['pending', 'running']

function fmtDate(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-GB')
}

// Trim a URL to its recognisable part; the full value stays in the title.
function shortUrl(url) {
  return url.replace(/^https?:\/\//i, '').replace(/\/$/, '')
}

// Cumulative replay savings. Sub-cent amounts get more precision so early
// savings don't all read as "$0.00".
function fmtSaved(value) {
  const n = Number(value) || 0
  if (n <= 0) return '—'
  return n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`
}

export default function Projects() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [modal, setModal] = useState(null) // {mode:'add'} | {mode:'edit', project}
  const [confirming, setConfirming] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [starting, setStarting] = useState(null)
  const [actionError, setActionError] = useState(null)

  const refresh = useCallback(async () => {
    try {
      setProjects(await listProjects())
      setLoadError(null)
    } catch (e) {
      setLoadError(String(e.message || e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  // Keep the status column honest while a test is running, but stop polling
  // once nothing is in flight.
  const hasActive = projects.some((p) => ACTIVE.includes(p.last_run_status))
  useEffect(() => {
    if (!hasActive) return undefined
    const id = setInterval(refresh, 3000)
    return () => clearInterval(id)
  }, [hasActive, refresh])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return projects.filter((p) => {
      const status = p.last_run_status || 'none'
      if (filter !== 'all' && status !== filter) return false
      if (!q) return true
      return (
        p.name.toLowerCase().includes(q) ||
        p.target_url.toLowerCase().includes(q) ||
        (p.model || '').toLowerCase().includes(q)
      )
    })
  }, [projects, query, filter])

  const handleRun = async (project) => {
    setStarting(project.id)
    setActionError(null)
    try {
      await runProjectTest(project.id)
      navigate(`/projects/${project.id}`)
    } catch (e) {
      setActionError(String(e.message || e))
      setStarting(null)
    }
  }

  const handleDelete = async () => {
    setDeleting(true)
    try {
      await deleteProject(confirming.id)
      setProjects((prev) => prev.filter((p) => p.id !== confirming.id))
      setConfirming(null)
    } catch (e) {
      setActionError(String(e.message || e))
    } finally {
      setDeleting(false)
    }
  }

  const handleSaved = (saved) => {
    setModal(null)
    setProjects((prev) => {
      const exists = prev.some((p) => p.id === saved.id)
      return exists ? prev.map((p) => (p.id === saved.id ? saved : p)) : [saved, ...prev]
    })
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h2 className="page-title">All Projects</h2>
          <p className="page-sub">Manage and monitor your quality assurance projects</p>
        </div>

        <div className="page-tools">
          <div className="search">
            <SearchIcon className="search-icon" />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name, URL, or model"
              aria-label="Search projects"
            />
          </div>

          <select
            className="select"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            aria-label="Filter by status"
          >
            {FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>

          <button type="button" className="btn btn-primary" onClick={() => setModal({ mode: 'add' })}>
            <PlusIcon />
            Add Project
          </button>
        </div>
      </header>

      {actionError && (
        <p className="banner banner-error" role="alert">
          {actionError}
        </p>
      )}
      {loadError && (
        <p className="banner banner-error" role="alert">
          Could not load projects: {loadError}
        </p>
      )}

      <section className="card table-card">
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Application URL</th>
                <th scope="col">Status</th>
                <th scope="col">Created</th>
                <th scope="col" className="col-center">Saved by replay</th>
                <th scope="col" className="col-center">Run Test</th>
                <th scope="col" className="col-center">Actions</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((p) => {
                const running = ACTIVE.includes(p.last_run_status)
                return (
                  <tr key={p.id}>
                    <td>
                      <span className="cell-name">{p.name}</span>
                      <span className="cell-model">{p.model}</span>
                    </td>
                    <td>
                      <a
                        className="cell-url"
                        href={p.target_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        title={p.target_url}
                      >
                        {shortUrl(p.target_url)}
                      </a>
                    </td>
                    <td>
                      <StatusBadge status={p.last_run_status} />
                    </td>
                    <td className="cell-date">{fmtDate(p.created_at)}</td>
                    <td className="col-center">
                      <span
                        className={p.total_cost_saved > 0 ? 'cell-saved' : 'muted'}
                        title="Cumulative USD saved by replaying this project's tests instead of re-running the AI"
                      >
                        {fmtSaved(p.total_cost_saved)}
                      </span>
                    </td>
                    <td className="col-center">
                      <button
                        type="button"
                        className="btn btn-run"
                        onClick={() => handleRun(p)}
                        disabled={running || starting === p.id}
                        title={
                          running
                            ? 'A test is already running for this project'
                            : `Run a test for ${p.name}. This replaces the previous result.`
                        }
                      >
                        {running ? 'Running…' : starting === p.id ? 'Starting…' : 'Run Test'}
                      </button>
                    </td>
                    <td>
                      <div className="row-actions">
                        <button
                          type="button"
                          className="icon-btn"
                          onClick={() => navigate(`/projects/${p.id}`)}
                          aria-label={`View ${p.name}`}
                          title="View"
                        >
                          <EyeIcon />
                        </button>
                        <button
                          type="button"
                          className="icon-btn"
                          onClick={() => setModal({ mode: 'edit', project: p })}
                          aria-label={`Edit ${p.name}`}
                          title="Edit"
                        >
                          <PencilIcon />
                        </button>
                        <button
                          type="button"
                          className="icon-btn icon-btn-danger"
                          onClick={() => setConfirming(p)}
                          aria-label={`Delete ${p.name}`}
                          title="Delete"
                        >
                          <TrashIcon />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {!loading && visible.length === 0 && (
          <div className="table-empty">
            {projects.length === 0 ? (
              <>
                <h3>No projects yet</h3>
                <p>Add the first application you want the agent to test.</p>
                <button type="button" className="btn btn-primary" onClick={() => setModal({ mode: 'add' })}>
                  <PlusIcon />
                  Add Project
                </button>
              </>
            ) : (
              <>
                <h3>No projects match these filters</h3>
                <p>Try a different search term or status.</p>
              </>
            )}
          </div>
        )}

        {loading && <div className="table-empty">Loading projects…</div>}
      </section>

      {modal && (
        <ProjectModal
          project={modal.mode === 'edit' ? modal.project : null}
          onClose={() => setModal(null)}
          onSaved={handleSaved}
        />
      )}

      {confirming && (
        <ConfirmDialog
          title={`Delete ${confirming.name}?`}
          body="This permanently removes the project along with every test run, finding, and recording it has. This cannot be undone."
          confirmLabel="Delete project"
          busy={deleting}
          onConfirm={handleDelete}
          onCancel={() => setConfirming(null)}
        />
      )}
    </div>
  )
}
