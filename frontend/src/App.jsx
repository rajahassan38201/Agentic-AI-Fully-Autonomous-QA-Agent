import { useState } from 'react'
import { Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom'
import Sidebar from './components/Sidebar.jsx'
import TopBar from './components/TopBar.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Projects from './pages/Projects.jsx'
import ProjectView from './pages/ProjectView.jsx'

// The page title shown in the top bar, keyed by route.
function useTitle() {
  const { pathname } = useLocation()
  if (pathname.startsWith('/projects/')) return 'Project'
  if (pathname.startsWith('/projects')) return 'Projects'
  return 'Dashboard'
}

// Remount the view when the project changes so its polling state starts clean.
function ProjectViewRoute() {
  const { projectId } = useParams()
  return <ProjectView key={projectId} projectId={projectId} />
}

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const title = useTitle()

  return (
    <div className={sidebarOpen ? 'app' : 'app app-nav-collapsed'}>
      <TopBar title={title} />

      <Sidebar open={sidebarOpen} onToggle={() => setSidebarOpen((v) => !v)} />

      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/:projectId" element={<ProjectViewRoute />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
    </div>
  )
}
