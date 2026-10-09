import { BellIcon, SearchIcon } from './Icons.jsx'

// The signed-in user is not wired to an auth system yet, so the identity shown
// here is fixed. It lives in one place so there is a single thing to replace
// when sign-in exists.
const USER = {
  name: 'Hafiz Hassan (LPS Contractor)',
  role: 'Admin',
  initials: 'HH',
}

function Wordmark() {
  return (
    <div className="brand">
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
