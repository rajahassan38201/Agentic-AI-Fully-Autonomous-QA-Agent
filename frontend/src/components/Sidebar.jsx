import { NavLink } from 'react-router-dom'
import {
  DashboardIcon,
  PanelIcon,
  ProjectsIcon,
  SettingsIcon,
  SignOutIcon,
} from './Icons.jsx'

const NAV = [
  { to: '/dashboard', label: 'Dashboard', Icon: DashboardIcon },
  { to: '/projects', label: 'Projects', Icon: ProjectsIcon },
]

export default function Sidebar({ open, onToggle }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <button
          type="button"
          className="icon-btn"
          onClick={onToggle}
          aria-label={open ? 'Collapse navigation' : 'Expand navigation'}
          aria-expanded={open}
        >
          <PanelIcon />
        </button>
      </div>

      <nav className="sidebar-nav" aria-label="Main">
        {NAV.map(({ to, label, Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => (isActive ? 'nav-item nav-item-active' : 'nav-item')}
            title={open ? undefined : label}
          >
            <Icon className="nav-icon" />
            <span className="nav-label">{label}</span>
          </NavLink>
        ))}

        {/* Settings has no screen behind it yet. It stays visible so the
            navigation reads complete, but is disabled rather than leading
            somewhere empty. */}
        <button
          type="button"
          className="nav-item nav-item-inert"
          disabled
          title="Settings are not available yet"
        >
          <SettingsIcon className="nav-icon" />
          <span className="nav-label">Settings</span>
        </button>
      </nav>

      <div className="sidebar-foot">
        <button
          type="button"
          className="nav-item nav-item-inert"
          disabled
          title="Sign out is not available yet"
        >
          <SignOutIcon className="nav-icon" />
          <span className="nav-label">Sign Out</span>
        </button>
      </div>
    </aside>
  )
}
