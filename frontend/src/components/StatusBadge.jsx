import { ActivityIcon, CheckCircleIcon, ClockIcon, StopIcon, XCircleIcon } from './Icons.jsx'

// A project with no runs yet has no status of its own, so the table shows the
// absence of a run rather than inventing one.
const STATUS = {
  completed: { label: 'Completed', tone: 'ok', Icon: CheckCircleIcon },
  failed: { label: 'Failed', tone: 'bad', Icon: XCircleIcon },
  running: { label: 'Running', tone: 'live', Icon: ActivityIcon },
  pending: { label: 'Queued', tone: 'live', Icon: ClockIcon },
  stopped: { label: 'Stopped', tone: 'neutral', Icon: StopIcon },
}

const NONE = { label: 'Not Running', tone: 'neutral', Icon: ClockIcon }

export default function StatusBadge({ status }) {
  const { label, tone, Icon } = STATUS[status] || NONE
  return (
    <span className={`status status-${tone}`}>
      <Icon className="status-icon" />
      {label}
    </span>
  )
}
