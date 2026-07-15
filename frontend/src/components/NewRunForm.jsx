import { useState } from 'react'
import { createRun } from '../api.js'

const MODELS = [
  'claude-opus-4-8',
  'claude-opus-4-7',
  'claude-opus-4-6',
  'claude-sonnet-4-6',
  'claude-sonnet-5',
  'claude-haiku-4-5',
]

const initial = {
  target_url: 'https://automationexercise.com/',
  goals: '',
  max_steps: 100,
  model: MODELS[0],
  auth_type: 'none',
  username: '',
  password: '',
  secret_key: '',
  login_instructions: '',
}

// Required (non-optional) fields per auth type. `login_instructions` is always
// optional, so it is never listed here.
const REQUIRED_AUTH_FIELDS = {
  basic: ['username', 'password'],
  form: ['username', 'password'],
  mfa: ['username', 'password', 'secret_key'],
}

const FIELD_LABELS = {
  username: 'Username / email',
  password: 'Password',
  secret_key: 'Secret key',
}

export default function NewRunForm({ onCreated }) {
  const [form, setForm] = useState(initial)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const update = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  // Returns an error message if a required field is missing, else null.
  const validate = () => {
    if (!form.target_url.trim()) return 'Target URL is required.'
    const required = REQUIRED_AUTH_FIELDS[form.auth_type] || []
    for (const field of required) {
      if (!String(form[field] || '').trim()) {
        return `${FIELD_LABELS[field]} is required for this authentication type.`
      }
    }
    return null
  }

  const submit = async (e) => {
    e.preventDefault()
    const validationError = validate()
    if (validationError) {
      setError(validationError)
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const payload = {
        target_url: form.target_url.trim(),
        goals: form.goals.trim() || null,
        max_steps: Number(form.max_steps) || 100,
        model: form.model,
        auth_type: form.auth_type,
        username: form.username || null,
        password: form.password || null,
        secret_key: form.secret_key || null,
        login_instructions: form.login_instructions || null,
      }
      const run = await createRun(payload)
      onCreated(run)
      // Keep the form for the next run, but clear the per-run goals and never
      // leave secrets sitting in the fields once they have been submitted.
      setForm({ ...form, goals: '', password: '', secret_key: '' })
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

      <label>Select Model</label>
      <select value={form.model} onChange={update('model')}>
        {MODELS.map((m) => (
          <option key={m} value={m}>{m}</option>
        ))}
      </select>

      <label>Authentication</label>
      <select value={form.auth_type} onChange={update('auth_type')}>
        <option value="none">None</option>
        <option value="basic">HTTP Basic</option>
        <option value="form">Form login</option>
        <option value="mfa">MFA Login</option>
      </select>

      {form.auth_type !== 'none' && (
        <div className="auth-fields">
          <input value={form.username} onChange={update('username')} placeholder="Username / email" required />
          <input type="password" value={form.password} onChange={update('password')} placeholder="Password" required />
          {form.auth_type === 'mfa' && (
            <input
              value={form.secret_key}
              onChange={update('secret_key')}
              placeholder="Secret key (base32 TOTP secret for 6-digit OTP)"
              required
            />
          )}
          {(form.auth_type === 'form' || form.auth_type === 'mfa') && (
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
