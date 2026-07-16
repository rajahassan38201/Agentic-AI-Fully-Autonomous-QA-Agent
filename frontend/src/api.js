const BASE = 'http://localhost:8000'
const API = `${BASE}/api`

// FastAPI reports errors as {detail: "..."}; surface that text so callers can
// show the real reason rather than a bare status code.
async function jsonOrThrow(res) {
  if (!res.ok) {
    let message = `HTTP ${res.status}`
    const text = await res.text()
    try {
      const body = JSON.parse(text)
      if (typeof body.detail === 'string') message = body.detail
      else if (text) message = text
    } catch {
      if (text) message = text
    }
    throw new Error(message)
  }
  if (res.status === 204) return null
  return res.json()
}

async function send(path, method, data) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return jsonOrThrow(res)
}

// --- Projects ---

export async function listProjects() {
  return jsonOrThrow(await fetch(`${API}/projects`))
}

export async function getProject(id) {
  return jsonOrThrow(await fetch(`${API}/projects/${id}`))
}

export async function createProject(data) {
  return send('/projects', 'POST', data)
}

export async function updateProject(id, data) {
  return send(`/projects/${id}`, 'PUT', data)
}

export async function deleteProject(id) {
  return jsonOrThrow(await fetch(`${API}/projects/${id}`, { method: 'DELETE' }))
}

export async function listProjectRuns(id) {
  return jsonOrThrow(await fetch(`${API}/projects/${id}/runs`))
}

// Start a test run from the project's saved configuration.
export async function runProjectTest(id) {
  return jsonOrThrow(await fetch(`${API}/projects/${id}/runs`, { method: 'POST' }))
}

// --- Runs ---

export async function getRun(id) {
  return jsonOrThrow(await fetch(`${API}/runs/${id}`))
}

export async function getFindings(id) {
  return jsonOrThrow(await fetch(`${API}/runs/${id}/findings`))
}

export async function getSteps(id) {
  return jsonOrThrow(await fetch(`${API}/runs/${id}/steps`))
}

// Ask a running run to stop. It finishes cleanly and saves everything —
// this is not a failure.
export async function stopRun(id) {
  return jsonOrThrow(await fetch(`${API}/runs/${id}/stop`, { method: 'POST' }))
}

// Live-preview frame URL. `tick` is a cache-buster so the <img> refreshes.
export function previewUrl(id, tick) {
  return `${API}/runs/${id}/preview?t=${tick}`
}

// Recorded session video (.webm) for a finished run.
export function videoUrl(id) {
  return `${API}/runs/${id}/video`
}
