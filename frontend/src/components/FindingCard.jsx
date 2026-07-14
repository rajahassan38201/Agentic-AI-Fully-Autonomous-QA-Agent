export default function FindingCard({ finding }) {
  const sev = (finding.severity || 'medium').toLowerCase()
  return (
    <div className={`finding sev-${sev}`}>
      <div className="finding-head">
        <span className={`sev-tag sev-${sev}`}>{sev}</span>
        <span className="finding-title">{finding.title}</span>
        {finding.category && <span className="finding-cat">{finding.category}</span>}
      </div>

      {finding.description && <p className="finding-desc">{finding.description}</p>}

      <dl className="finding-details">
        {finding.steps_to_reproduce && (
          <>
            <dt>Steps</dt>
            <dd>{finding.steps_to_reproduce}</dd>
          </>
        )}
        {finding.expected && (
          <>
            <dt>Expected</dt>
            <dd>{finding.expected}</dd>
          </>
        )}
        {finding.actual && (
          <>
            <dt>Actual</dt>
            <dd>{finding.actual}</dd>
          </>
        )}
        {finding.evidence && (
          <>
            <dt>Evidence</dt>
            <dd><code>{finding.evidence}</code></dd>
          </>
        )}
      </dl>
    </div>
  )
}
