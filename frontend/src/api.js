const BASE = 'http://localhost:8000'
const API = `${BASE}/api`

async function jsonOrThrow(res) {
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  return res.json()
}

export async function createRun(data) {
  const res = await fetch(`${API}/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return jsonOrThrow(res)
}

export async function listRuns() {
  return jsonOrThrow(await fetch(`${API}/runs`))
}

export async function getRun(id) {
  return jsonOrThrow(await fetch(`${API}/runs/${id}`))
}

export async function getFindings(id) {
  return jsonOrThrow(await fetch(`${API}/runs/${id}/findings`))
}

export async function getSteps(id) {
  return jsonOrThrow(await fetch(`${API}/runs/${id}/steps`))
}

export async function deleteRun(id) {
  const res = await fetch(`${API}/runs/${id}`, { method: 'DELETE' })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  return true
}

// Live-preview frame URL. `tick` is a cache-buster so the <img> refreshes.
export function previewUrl(id, tick) {
  return `${API}/runs/${id}/preview?t=${tick}`
}

// Recorded session video (.webm) for a finished run.
export function videoUrl(id) {
  return `${API}/runs/${id}/video`
}
