import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from './api.js'
import Dashboard from './pages/Dashboard.jsx'
import Review from './pages/Review.jsx'
import History from './pages/History.jsx'
import Insights from './pages/Insights.jsx'
import Categories from './pages/Categories.jsx'
import Settings from './pages/Settings.jsx'
import Guides from './pages/Guides.jsx'

const NAV = [
  ['dashboard', 'Dashboard'],
  ['review', 'Review'],
  ['history', 'History'],
  ['insights', "What's working"],
  ['categories', 'Categories'],
  ['settings', 'Settings'],
  ['guides', 'Guides'],
]

export const AppContext = createContext(null)
export const useApp = () => useContext(AppContext)

function parseHash() {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const [path, query = ''] = raw.split('?')
  const [page = 'dashboard', ...rest] = path.split('/')
  return { page: page || 'dashboard', sub: rest.join('/'), params: new URLSearchParams(query) }
}

export function navigate(to) {
  window.location.hash = to.startsWith('#') ? to : `#/${to}`
}

export default function App() {
  const [route, setRoute] = useState(parseHash())
  const [status, setStatus] = useState(null)
  const [toast, setToast] = useState(null)

  useEffect(() => {
    const onHash = () => setRoute(parseHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await api.get('/api/status'))
    } catch (e) {
      setStatus((s) => (s ? { ...s, offline: true } : { offline: true }))
    }
  }, [])

  useEffect(() => {
    refreshStatus()
    const t = setInterval(refreshStatus, 3000)
    return () => clearInterval(t)
  }, [refreshStatus])

  const notify = useCallback((message, kind = 'info') => {
    setToast({ message, kind, id: Date.now() })
  }, [])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), toast.kind === 'error' ? 7000 : 3500)
    return () => clearTimeout(t)
  }, [toast])

  const review = status?.items?.review || 0
  const pages = { dashboard: Dashboard, review: Review, history: History, insights: Insights,
    categories: Categories, settings: Settings, guides: Guides }
  const Page = pages[route.page] || Dashboard

  return (
    <AppContext.Provider value={{ status, refreshStatus, notify, route }}>
      <div className="shell">
        <aside className="sidebar">
          <a className="brand" href="#/dashboard">
            <img src="/favicon.svg" alt="" width="28" height="28" />
            <span>ClipPilot</span>
          </a>
          <nav>
            {NAV.map(([key, label]) => (
              <a key={key} href={`#/${key}`} className={route.page === key ? 'active' : ''}>
                {label}
                {key === 'review' && review > 0 && <span className="badge">{review}</span>}
              </a>
            ))}
          </nav>
          <div className="sidebar-foot">
            <StatusDot status={status} />
            <div className="muted small">v{status?.version || '…'} · runs on this computer only</div>
          </div>
        </aside>
        <main className="content">
          {status?.offline && <div className="banner error">Can't reach the ClipPilot engine. Is the app still running?</div>}
          <Page />
        </main>
      </div>
      {toast && (
        <div className={`toast ${toast.kind}`} role="status" onClick={() => setToast(null)}>
          {toast.message}
        </div>
      )}
    </AppContext.Provider>
  )
}

export function StatusDot({ status, large }) {
  const state = status?.offline ? 'offline' : status?.state || 'loading'
  const labels = { stopped: 'Stopped', idle: 'Running · idle', working: 'Running · working', paused: 'Paused',
    offline: 'Offline', loading: 'Connecting…' }
  return (
    <div className={`status-dot ${state} ${large ? 'large' : ''}`}>
      <span className="dot" />
      <span>{labels[state] || state}</span>
    </div>
  )
}
