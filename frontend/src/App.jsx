import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { api, fmtDuration } from './api.js'
import { onScroll, scrollToTop } from './fx/motion.js'
import { Sticker } from './fx/components.jsx'
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
  ['insights', 'Insights'],
  ['categories', 'Categories'],
  ['settings', 'Settings'],
  ['guides', 'Guides'],
]
const PAGES = { dashboard: Dashboard, review: Review, history: History, insights: Insights,
  categories: Categories, settings: Settings, guides: Guides }

export const AppContext = createContext(null)
export const useApp = () => useContext(AppContext)

function parseHash() {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const [path, query = ''] = raw.split('?')
  const [page = 'dashboard', ...rest] = path.split('/')
  return { page: PAGES[page] ? page : 'dashboard', sub: rest.join('/'), params: new URLSearchParams(query) }
}

export function engineState(status) {
  if (!status || status.offline) return 'offline'
  return status.state || 'stopped'
}
const STATE_LABEL = { stopped: 'Stopped', idle: 'Running', working: 'Working', paused: 'Paused', offline: 'Offline' }

function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(t)
  }, [ms])
  return now
}

function Dock({ status, refreshStatus, notify }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const peak = useRef({})
  const now = useNow()
  const state = engineState(status)
  const nu = status?.next_upload
  const left = nu ? Math.max(0, (new Date(nu.at).getTime() - now) / 1000) : null
  if (nu && left != null) peak.current[nu.item_id] = Math.max(peak.current[nu.item_id] || 0, left, 1)
  const progress = nu ? 1 - left / (peak.current[nu.item_id] || 1) : 0
  const C = 2 * Math.PI * 16

  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('click', close)
    return () => document.removeEventListener('click', close)
  }, [])

  const toggle = async () => {
    try {
      await api.post(status?.running ? '/api/engine/stop' : '/api/engine/start')
      await refreshStatus()
      notify(status?.running ? 'Stopped' : 'Started. Looking for clips now.')
    } catch (e) { notify(e.message, 'error') }
  }
  const label = !status ? 'Connecting' : nu
    ? (left > 0 ? `Next upload ${fmtDuration(left)}` : status.running ? 'Uploading next' : 'Upload ready · press start')
    : (status.running ? (Object.values(status.activity || {}).find((a) => a !== 'idle') || 'Watching for clips') : 'Press start to go')

  return (
    <div ref={ref} className={`dock ${open ? 'open' : ''} ${status?.running ? 'on' : ''} ${state === 'paused' ? 'paused' : ''}`}>
      <div className="dock-panel" role="menu">
        <button className={`btn small ${status?.running ? 'danger' : 'primary'}`} onClick={toggle} data-magnetic="0.15">
          {status?.running ? 'Stop engine' : 'Start engine'}
        </button>
        <a className="btn small" href="#/review" onClick={() => setOpen(false)}>Review · {status?.items?.review || 0}</a>
      </div>
      <button type="button" className="dock-pill" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="dock-idx"><span className="led" />{STATE_LABEL[state] || state}</span>
        <span className="dock-name">{label.length > 34 ? `${label.slice(0, 33)}…` : label}</span>
        <span className="dock-ring" aria-hidden="true">
          <svg viewBox="0 0 34 34"><circle cx="17" cy="17" r="16" strokeDasharray={C} strokeDashoffset={C * (1 - progress)} /></svg>
          <i />
        </span>
      </button>
    </div>
  )
}

export default function App() {
  const [route, setRoute] = useState(parseHash())
  const [status, setStatus] = useState(null)
  const [toast, setToast] = useState(null)
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const onHash = () => {
      const next = parseHash()
      setRoute((prev) => {
        if (prev.page !== next.page || prev.sub !== next.sub) scrollToTop()
        return next
      })
      document.documentElement.classList.remove('menu-open')
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  useEffect(() => onScroll((y) => setScrolled(y > 24)), [])

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await api.get('/api/status'))
    } catch {
      setStatus((s) => (s ? { ...s, offline: true } : { offline: true }))
    }
  }, [])
  useEffect(() => {
    refreshStatus()
    const t = setInterval(refreshStatus, 3000)
    return () => clearInterval(t)
  }, [refreshStatus])
  useEffect(() => {
    document.documentElement.classList.toggle('engine-on', !!status?.running)
  }, [status?.running])

  const notify = useCallback((message, kind = 'info') => setToast({ message, kind, id: Date.now() }), [])
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), toast.kind === 'error' ? 7000 : 3500)
    return () => clearTimeout(t)
  }, [toast])

  const state = engineState(status)
  const review = status?.items?.review || 0
  const Page = PAGES[route.page]

  return (
    <AppContext.Provider value={{ status, refreshStatus, notify, route }}>
      <header className={`topbar ${scrolled ? 'is-scrolled' : ''}`}>
        <a href="#/dashboard" className="brand" aria-label="clipped dashboard">
          <Sticker />
          <span>clipped</span>
          <span className="brand-dot" />
        </a>
        <nav className="topnav" aria-label="Primary">
          {NAV.map(([key, label]) => (
            <a key={key} href={`#/${key}`} className={route.page === key ? 'active' : ''}>
              <span data-scramble="">{label}</span>
              {key === 'review' && review > 0 && <span className="badge" key={review}>{review}</span>}
            </a>
          ))}
        </nav>
        <div className="topbar-tools">
          <a href="#/dashboard" className={`pill-btn ${status?.running ? (state === 'paused' ? 'paused' : 'on') : 'off'}`} data-magnetic="0.2"
            title={status?.running ? 'Engine running' : 'Engine stopped'}>
            <span className="led" /><span className="pill-label">{STATE_LABEL[state] || state}</span>
          </a>
          <button className="menu-btn" type="button" aria-expanded="false" data-magnetic="0.2"
            onClick={(e) => {
              const open = document.documentElement.classList.toggle('menu-open')
              e.currentTarget.setAttribute('aria-expanded', String(open))
            }}>
            <span>Menu</span>
            <span className="menu-btn-dots" aria-hidden="true"><i /><i /><i /><i /></span>
          </button>
        </div>
      </header>

      <nav className="menu" aria-label="Menu" data-lenis-prevent="">
        {NAV.map(([key, label], i) => (
          <a key={key} href={`#/${key}`} className={route.page === key ? 'active' : ''} style={{ '--i': i }}>
            <small>{String(i + 1).padStart(2, '0')}</small>{label}
          </a>
        ))}
      </nav>

      <main className="app-main">
        {status?.offline && <div className="banner error" style={{ marginBottom: 18 }}>Can't reach the clipped engine. Is the app still running?</div>}
        <div key={`${route.page}/${route.sub}`} className="page-enter">
          <Page />
        </div>
      </main>

      <Dock status={status} refreshStatus={refreshStatus} notify={notify} />

      {toast && (
        <div key={toast.id} className={`toast ${toast.kind}`} role="status" style={{ '--t': toast.kind === 'error' ? '7s' : '3.5s' }}
          onClick={() => setToast(null)}>
          {toast.message}
        </div>
      )}
    </AppContext.Provider>
  )
}
