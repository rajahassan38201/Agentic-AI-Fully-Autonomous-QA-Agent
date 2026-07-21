import { BellIcon, SearchIcon } from './Icons.jsx'

// The signed-in user is not wired to an auth system yet, so the identity shown
// here is fixed. It lives in one place so there is a single thing to replace
// when sign-in exists.
const USER = {
  name: 'Hafiz Hassan (LPS Contractor)',
  role: 'Admin',
  initials: 'MC',
}

function Wordmark() {
  return (
    <div className="brand">
      <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        {[
          [6, 6], [12, 4], [18, 6], [24, 9],
          [4, 12], [10, 11], [16, 12], [22, 15],
          [6, 18], [12, 17], [18, 19],
          [8, 24], [14, 23],
        ].map(([cx, cy], i) => (
          <circle key={i} cx={cx} cy={cy} r="2.1" />
        ))}
      </svg>
      <span className="brand-name">QA</span>
      <span className="brand-divider" aria-hidden="true" />
      <span className="brand-tagline">
        AI Agentic QA
        <br />
        Platform
      </span>
    </div>
  )
}

export default function TopBar({ title }) {
  return (
    <header className="topbar">
      <Wordmark />

      <h1 className="topbar-title">{title}</h1>

      <div className="topbar-search">
        <SearchIcon className="topbar-search-icon" />
        <input type="search" placeholder="Search workspace" aria-label="Search workspace" />
      </div>

      <div className="topbar-right">
        <button type="button" className="icon-btn topbar-bell" aria-label="Notifications">
          <BellIcon />
          <span className="topbar-bell-dot" aria-hidden="true" />
        </button>

        <span className="topbar-sep" aria-hidden="true" />

        <div className="topbar-user">
          <span className="avatar" aria-hidden="true">{USER.initials}</span>
          <span className="topbar-user-text">
            <span className="topbar-user-name">{USER.name}</span>
            <span className="topbar-user-role">{USER.role}</span>
          </span>
        </div>
      </div>
    </header>
  )
}
