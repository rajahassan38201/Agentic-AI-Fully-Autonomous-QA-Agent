import { useEffect, useRef, useState } from 'react'
import { createProject, updateProject } from '../api.js'

const MODELS = [
  'claude-opus-4-8',
  'claude-opus-4-7',
  'claude-opus-4-6',
  'claude-sonnet-4-6',
  'claude-sonnet-5',
  'claude-haiku-4-5',
]

const AUTH_TYPES = [
  { value: 'none', label: 'None' },
  { value: 'basic', label: 'HTTP Basic' },
  { value: 'form', label: 'Form login' },
  { value: 'mfa', label: 'MFA login' },
]

const BLANK = {
  name: '',
  target_url: '',
  goals: '',
  max_steps: 100,
  model: MODELS[0],
  auth_type: 'none',
  username: '',
  password: '',
  secret_key: '',
  login_instructions: '',
}

// Credentials required per auth type. `login_instructions` is always optional.
const REQUIRED_BY_AUTH = {
  basic: ['username', 'password'],
  form: ['username', 'password'],
  mfa: ['username', 'password', 'secret_key'],
}

const LABELS = {
  username: 'Username or email',
  password: 'Password',
  secret_key: 'Secret key',
}

// Map a saved project onto form state. Stored credentials never come back from
// the API, so their inputs start empty and only overwrite when retyped.
function toForm(project) {
  if (!project) return BLANK
  return {
    ...BLANK,
    name: project.name || '',
    target_url: project.target_url || '',
    goals: project.goals || '',
    max_steps: project.max_steps ?? 100,
    model: MODELS.includes(project.model) ? project.model : MODELS[0],
    auth_type: project.auth_type || 'none',
    username: project.username || '',
    login_instructions: project.login_instructions || '',
  }
}

export default function ProjectModal({ project, onClose, onSaved }) {
  const editing = Boolean(project)
  const [form, setForm] = useState(() => toForm(project))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const firstFieldRef = useRef(null)

  useEffect(() => {
    firstFieldRef.current?.focus()
  }, [])

  // Escape closes the dialog, matching the Cancel button.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const validate = () => {
    if (!form.name.trim()) return 'Enter a project name.'
    if (!form.target_url.trim()) return 'Enter the application URL.'
    if (!/^https?:\/\//i.test(form.target_url.trim())) {
      return 'The application URL must start with http:// or https://'
    }
    const steps = Number(form.max_steps)
    if (!Number.isFinite(steps) || steps < 1 || steps > 5000) {
      return 'Max steps must be between 1 and 5000.'
    }
    for (const field of REQUIRED_BY_AUTH[form.auth_type] || []) {
      // On edit, a stored credential counts as already supplied.
      const stored =
        editing &&
        ((field === 'password' && project.has_password) ||
          (field === 'secret_key' && project.has_secret_key))
      if (!String(form[field] || '').trim() && !stored) {
        return `${LABELS[field]} is required for this authentication type.`
      }
    }
    return null
  }

  const submit = async (e) => {
    e.preventDefault()
    const problem = validate()
    if (problem) {
      setError(problem)
      return
    }
    setSaving(true)
    setError(null)
    try {
      const payload = {
        name: form.name.trim(),
        target_url: form.target_url.trim(),
        goals: form.goals.trim() || null,
        max_steps: Number(form.max_steps),
        model: form.model,
        auth_type: form.auth_type,
        username: form.auth_type === 'none' ? null : form.username.trim() || null,
        password: form.password || null,
        secret_key: form.auth_type === 'mfa' ? form.secret_key || null : null,
        login_instructions: form.login_instructions.trim() || null,
      }
      const saved = editing
        ? await updateProject(project.id, payload)
        : await createProject(payload)
      onSaved(saved)
    } catch (err) {
      setError(String(err.message || err))
      setSaving(false)
    }
  }

  const needsAuth = form.auth_type !== 'none'
  const isMfa = form.auth_type === 'mfa'
  const showInstructions = form.auth_type === 'form' || isMfa

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="project-modal-title">
        <header className="modal-head">
          <h2 id="project-modal-title">{editing ? 'Edit project' : 'Add project'}</h2>
          <p className="modal-sub">
            {editing
              ? 'Update the configuration the agent uses for this application.'
              : 'Tell the agent what to test and how to sign in.'}
          </p>
        </header>

        <form className="modal-body" onSubmit={submit}>
          <div className="field">
            <label htmlFor="p-name">Project name</label>
            <input
              id="p-name"
              ref={firstFieldRef}
              value={form.name}
              onChange={update('name')}
              placeholder="Automation Excercise"
            />
          </div>

          <div className="field">
            <label htmlFor="p-url">Application URL</label>
            <input
              id="p-url"
              value={form.target_url}
              onChange={update('target_url')}
              placeholder="https://example.com"
            />
          </div>

          <div className="field">
            <label htmlFor="p-goals">
              Goals <span className="field-optional">optional</span>
            </label>
            <textarea
              id="p-goals"
              rows={3}
              value={form.goals}
              onChange={update('goals')}
              placeholder="Test signup, login, search and checkout. Leave blank for a full comprehensive test."
            />
          </div>

          <div className="field-row">
            <div className="field">
              <label htmlFor="p-steps">Max steps</label>
              <input
                id="p-steps"
                type="number"
                min="1"
                max="5000"
                value={form.max_steps}
                onChange={update('max_steps')}
              />
            </div>

            <div className="field">
              <label htmlFor="p-model">Model</label>
              <select id="p-model" value={form.model} onChange={update('model')}>
                {MODELS.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="field">
            <label htmlFor="p-auth">Authentication</label>
            <select id="p-auth" value={form.auth_type} onChange={update('auth_type')}>
              {AUTH_TYPES.map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>
          </div>

          {needsAuth && (
            <div className="auth-block">
              <p className="auth-note">
                Credentials are encrypted before they are stored and are only decrypted
                when a test runs.
              </p>

              <div className="field">
                <label htmlFor="p-user">{LABELS.username}</label>
                <input
                  id="p-user"
                  value={form.username}
                  onChange={update('username')}
                  autoComplete="off"
                  placeholder="qa@example.com"
                />
              </div>

              <div className="field">
                <label htmlFor="p-pass">{LABELS.password}</label>
                <input
                  id="p-pass"
                  type="password"
                  value={form.password}
                  onChange={update('password')}
                  autoComplete="new-password"
                  placeholder={
                    editing && project.has_password ? 'Saved — type to replace' : 'Password'
                  }
                />
              </div>

              {isMfa && (
                <div className="field">
                  <label htmlFor="p-secret">{LABELS.secret_key}</label>
                  <input
                    id="p-secret"
                    value={form.secret_key}
                    onChange={update('secret_key')}
                    autoComplete="off"
                    placeholder={
                      editing && project.has_secret_key
                        ? 'Saved — type to replace'
                        : 'Base32 TOTP secret for the 6-digit code'
                    }
                  />
                </div>
              )}

              {showInstructions && (
                <div className="field">
                  <label htmlFor="p-instr">
                    Login instructions <span className="field-optional">optional</span>
                  </label>
                  <textarea
                    id="p-instr"
                    rows={2}
                    value={form.login_instructions}
                    onChange={update('login_instructions')}
                    placeholder="Click Sign in, then use the email form."
                  />
                </div>
              )}
            </div>
          )}

          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}

          <footer className="modal-foot">
            <button type="button" className="btn btn-quiet" onClick={onClose} disabled={saving}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? 'Saving…' : editing ? 'Save changes' : 'Add project'}
            </button>
          </footer>
        </form>
      </div>
    </div>
  )
}
