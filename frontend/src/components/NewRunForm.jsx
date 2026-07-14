import { useState } from 'react'
import { createRun } from '../api.js'

const initial = {
  target_url: 'https://automationexercise.com/',
  goals: '',
  max_steps: 100,
  auth_type: 'none',
  username: '',
  password: '',
  login_instructions: '',
}

export default function NewRunForm({ onCreated }) {
  const [form, setForm] = useState(initial)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const update = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const payload = {
        target_url: form.target_url.trim(),
        goals: form.goals.trim() || null,
        max_steps: Number(form.max_steps) || 100,
        auth_type: form.auth_type,
        username: form.username || null,
        password: form.password || null,
        login_instructions: form.login_instructions || null,
      }
      const run = await createRun(payload)
      onCreated(run)
      setForm({ ...initial, target_url: form.target_url })
    } catch (err) {
      setError(String(err.message || err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="card form" onSubmit={submit}>
      <h3>New test run</h3>

      <label>Target URL</label>
      <input value={form.target_url} onChange={update('target_url')} placeholder="https://example.com" required />

      <label>Goals (optional)</label>
      <textarea
        value={form.goals}
        onChange={update('goals')}
        rows={3}
        placeholder="e.g. Test signup, login, search and checkout. Leave blank for a full comprehensive test."
      />

      <label>Max steps</label>
      <input type="number" min="5" max="5000" value={form.max_steps} onChange={update('max_steps')} />

      <label>Authentication</label>
      <select value={form.auth_type} onChange={update('auth_type')}>
        <option value="none">None</option>
        <option value="basic">HTTP Basic</option>
        <option value="form">Form login</option>
      </select>

      {form.auth_type !== 'none' && (
        <div className="auth-fields">
          <input value={form.username} onChange={update('username')} placeholder="Username / email" />
          <input type="password" value={form.password} onChange={update('password')} placeholder="Password" />
          {form.auth_type === 'form' && (
            <textarea
              value={form.login_instructions}
              onChange={update('login_instructions')}
              rows={2}
              placeholder="Optional: where/how to log in (e.g. 'Click Sign in, then use the email form')."
            />
          )}
        </div>
      )}

      {error && <div className="error">{error}</div>}

      <button type="submit" disabled={submitting}>
        {submitting ? 'Starting…' : 'Run test'}
      </button>
    </form>
  )
}
