export default function StepLog({ steps }) {
  if (!steps.length) return <p className="muted">No steps yet…</p>
  return (
    <ul className="steplog">
      {steps.map((s) => (
        <li key={s.id} className={s.is_error ? 'step step-error' : 'step'}>
          <span className={s.tool_name === 'message' ? 'step-tool step-msg' : 'step-tool'}>
            {s.tool_name}
          </span>
          {s.tool_input && s.tool_name !== 'message' && (
            <code className="step-input">{s.tool_input}</code>
          )}
          {s.result_summary && <div className="step-result">{s.result_summary}</div>}
        </li>
      ))}
    </ul>
  )
}
