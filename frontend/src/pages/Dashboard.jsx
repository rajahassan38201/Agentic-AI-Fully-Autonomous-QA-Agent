import {
  ActivityIcon,
  BoltIcon,
  BroadcastIcon,
  CheckCircleIcon,
  ClockIcon,
  DatabaseIcon,
  RefreshIcon,
  SendIcon,
  SparkIcon,
  XCircleIcon,
} from '../components/Icons.jsx'

// This page is a static overview: nothing here is wired to live infrastructure
// yet. Every value is defined here so there is one place to replace when the
// real telemetry endpoints exist.
const SERVICES = [
  { name: 'Database', detail: 'PostgreSQL', Icon: DatabaseIcon },
  { name: 'Service Bus', detail: 'Azure Service Bus', Icon: SendIcon },
  { name: 'SignalR', detail: 'Real-time hub', Icon: BroadcastIcon },
  { name: 'gRPC', detail: 'Log streaming', Icon: BoltIcon, refresh: true },
]

const TRENDS = [
  { day: 'Mon', passed: 520, failed: 24 },
  { day: 'Tue', passed: 610, failed: 18 },
  { day: 'Wed', passed: 580, failed: 30 },
  { day: 'Thu', passed: 690, failed: 22 },
  { day: 'Fri', passed: 620, failed: 26 },
  { day: 'Sat', passed: 740, failed: 16 },
  { day: 'Sun', passed: 780, failed: 20 },
]

const ACTIVITY = [
  { title: 'Payment Gateway API', agent: 'Analyzer Agent', state: 'completed', when: '2 min ago' },
  { title: 'Checkout Flow', agent: 'Crawler Agent', state: 'failed', when: '15 min ago' },
  { title: 'Weekly Security Audit', agent: 'Crawler Agent', state: 'generated', when: '1 hour ago' },
  { title: 'User Auth Service', agent: 'Analyzer Agent', state: 'in progress', when: '2 hours ago' },
]

const ACTIVITY_ICON = {
  completed: { Icon: CheckCircleIcon, tone: 'ok' },
  failed: { Icon: XCircleIcon, tone: 'bad' },
  generated: { Icon: ClockIcon, tone: 'neutral' },
  'in progress': { Icon: ActivityIcon, tone: 'info' },
}

const Y_TICKS = [1000, 750, 500, 250]
const Y_MAX = 1000

function ServiceCard({ name, detail, Icon, refresh }) {
  return (
    <section className="card service-card">
      <h2 className="service-name">{name}</h2>
      <div className="service-row">
        <Icon className="service-icon" />
        <span className="pill pill-ok">
          <CheckCircleIcon className="pill-icon" />
          Connected
        </span>
      </div>
      <p className="service-detail">{detail}</p>
      {refresh && (
        <button type="button" className="btn btn-ghost service-refresh">
          <RefreshIcon />
          Refresh
        </button>
      )}
    </section>
  )
}

function TrendChart() {
  return (
    <div className="chart">
      <div className="chart-grid" aria-hidden="true">
        {Y_TICKS.map((t) => (
          <div className="chart-gridline" key={t} style={{ bottom: `${(t / Y_MAX) * 100}%` }}>
            <span className="chart-tick">{t}</span>
          </div>
        ))}
      </div>

      <ol className="chart-bars">
        {TRENDS.map(({ day, passed, failed }) => (
          <li className="chart-col" key={day}>
            <div className="chart-pair">
              <span
                className="bar bar-passed"
                style={{ height: `${(passed / Y_MAX) * 100}%` }}
                title={`${day}: ${passed} passed`}
              />
              <span
                className="bar bar-failed"
                style={{ height: `${(failed / Y_MAX) * 100}%` }}
                title={`${day}: ${failed} failed`}
              />
            </div>
            <span className="chart-label">{day}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

export default function Dashboard() {
  return (
    <div className="page dashboard">
      <div className="service-grid">
        {SERVICES.map((s) => (
          <ServiceCard key={s.name} {...s} />
        ))}
      </div>

      <div className="dash-grid">
        <section className="card panel">
          <header className="panel-head">
            <div>
              <h2 className="panel-title">Test Execution Trends</h2>
              <p className="panel-sub">7-day automated test activity</p>
            </div>
            <span className="panel-badge" aria-hidden="true">
              <ActivityIcon />
            </span>
          </header>

          <TrendChart />

          <ul className="chart-legend">
            <li>
              <span className="legend-swatch legend-passed" aria-hidden="true" />
              Passed
            </li>
            <li>
              <span className="legend-swatch legend-failed" aria-hidden="true" />
              Failed
            </li>
          </ul>
        </section>

        <section className="card panel">
          <header className="panel-head">
            <div>
              <h2 className="panel-title">Agent Activity Stream</h2>
              <p className="panel-sub">Real-time execution updates</p>
            </div>
            <span className="panel-badge" aria-hidden="true">
              <SparkIcon />
            </span>
          </header>

          <ul className="stream">
            {ACTIVITY.map((a) => {
              const { Icon, tone } = ACTIVITY_ICON[a.state]
              return (
                <li className={`stream-item stream-${tone}`} key={a.title}>
                  <span className="stream-icon">
                    <Icon />
                  </span>
                  <span className="stream-text">
                    <span className="stream-title">{a.title}</span>
                    <span className="stream-meta">
                      {a.agent} • {a.state}
                    </span>
                  </span>
                  <span className="stream-when">{a.when}</span>
                </li>
              )
            })}
          </ul>
        </section>
      </div>
    </div>
  )
}
