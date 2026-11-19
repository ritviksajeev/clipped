import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { api, fmtDuration, fmtTime, hasNativeWindow, windowControl } from './api.js'
import { useNow } from './fx.js'
import { Sticker } from './stickers.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Review from './pages/Review.jsx'
import History from './pages/History.jsx'
import Insights from './pages/Insights.jsx'
import Categories from './pages/Categories.jsx'
import Settings from './pages/Settings.jsx'
import Guides from './pages/Guides.jsx'

// Every place in the app, with its sticker. `r` is the sticker's resting tilt.
export const NAV = [
  { key: 'dashboard', label: 'Dashboard', note: 'engine', r: -7 },
  { key: 'review', label: 'Review', note: 'the queue', r: 5 },
  { key: 'categories', label: 'Categories', note: 'your games', r: -4 },
  { key: 'history', label: 'History', note: 'uploads', r: 6 },
  { key: 'insights', label: 'Insights', note: 'what works', r: -5 },
  { key: 'settings', label: 'Settings', note: 'tune it', r: 4 },
  { key: 'guides', label: 'Guides', note: 'set up', r: -3 },
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
export const STATE_LABEL = { stopped: 'Stopped', idle: 'Running', working: 'Working', paused: 'Paused', offline: 'Offline' }

// ---------------------------------------------------------------- title bar

function Icon({ d, size = 10 }) {
  return <svg width={size} height={size} viewBox="0 0 10 10" fill="none" aria-hidden="true">{d}</svg>
}

function TitleBar({ status, page, menuOpen, onMenu, native }) {
  const state = engineState(status)
  const [maxed, setMaxed] = useState(false)
  const nav = NAV.find((n) => n.key === page)
  const drag = 'pywebview-drag-region'
  return (
    <header className={`titlebar ${drag}`} onDoubleClick={(e) => {
      if (native && e.target.classList.contains(drag)) { windowControl('toggle_maximize'); setMaxed((m) => !m) }
    }}>
      <a href="#/dashboard" className="brand" aria-label="clipped dashboard">
        <span className="brand-stk"><Sticker name="clipped" /></span>
        <span className={`brand-word ${drag}`}>clipped<i /></span>
      </a>
      <span className={`tb-crumb ${drag}`}>/ {nav?.label.toLowerCase()}</span>
      <span className={`tb-space ${drag}`} />
      <a href="#/dashboard" className={`state-pill ${status?.running ? (state === 'paused' ? 'paused' : 'on') : 'off'}`}
        title={status?.running ? 'Engine running' : 'Engine stopped'}>
        <span className="led" /><span>{STATE_LABEL[state] || state}</span>
      </a>
      <button className={`menu-btn ${menuOpen ? 'open' : ''}`} type="button" aria-expanded={menuOpen} aria-controls="app-menu" onClick={onMenu}>
        <span>{menuOpen ? 'Close' : 'Menu'}</span>
        <span className="menu-btn-dots" aria-hidden="true"><i /><i /><i /><i /></span>
      </button>
      {native && (
        <div className="win-ctl">
          <button type="button" aria-label="Minimise" onClick={() => windowControl('minimize')}>
            <Icon d={<path d="M1 5h8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />} />
          </button>
          <button type="button" aria-label={maxed ? 'Restore' : 'Maximise'} onClick={() => { windowControl('toggle_maximize'); setMaxed((m) => !m) }}>
            <Icon d={maxed
              ? <><rect x="1.2" y="3" width="5.8" height="5.8" rx="1" stroke="currentColor" strokeWidth="1.1" /><path d="M3.2 3V1.8a.6.6 0 0 1 .6-.6h4.4a.6.6 0 0 1 .6.6v4.4a.6.6 0 0 1-.6.6H7" stroke="currentColor" strokeWidth="1.1" /></>
              : <rect x="1.2" y="1.2" width="7.6" height="7.6" rx="1.2" stroke="currentColor" strokeWidth="1.1" />} />
          </button>
          <button type="button" className="close" aria-label="Close" onClick={() => windowControl('close')}>
            <Icon d={<path d="M1.5 1.5l7 7M8.5 1.5l-7 7" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />} />
          </button>
        </div>
      )}
    </header>
  )
}

// ---------------------------------------------------------------- sticker rail

function Rail({ page, status, onEngine, busy }) {
  const review = status?.items?.review || 0
  const failed = status?.items?.failed || 0
  return (
    <nav className="rail" aria-label="Sections">
      <div className="rail-list">
        {NAV.map((n, i) => {
          const badge = n.key === 'review' ? review : 0
          return (
            <a key={n.key} href={`#/${n.key}`} className={`rail-item ${page === n.key ? 'active' : ''}`}
              style={{ '--r': `${n.r}deg`, '--i': i }} aria-label={n.label} aria-current={page === n.key ? 'page' : undefined}>
              <Sticker name={n.key} />
              {badge > 0 && <span className="rail-badge" key={badge}>{badge}</span>}
              {n.key === 'review' && !badge && failed > 0 && <span className="rail-badge warn">!</span>}
              <span className="tip">{n.label}<small>{n.note}</small></span>
            </a>
          )
        })}
      </div>
      <button type="button" className={`rail-engine ${status?.running ? 'on' : ''}`} onClick={onEngine} disabled={busy || !status || status.offline}
        aria-label={status?.running ? 'Stop the engine' : 'Start the engine'}>
        <span className="rail-engine-ring" aria-hidden="true" />
        <Sticker name="power" />
        <span className="tip">{status?.running ? 'Stop engine' : 'Start engine'}<small>{status?.running ? 'running' : 'stopped'}</small></span>
      </button>
    </nav>
  )
}

// ---------------------------------------------------------------- the sticker menu (evzero.org style)

function Menu({ open, page, status, onClose, onEngine }) {
  const first = useRef(null)
  useEffect(() => {
    if (!open) return
    const t = setTimeout(() => first.current?.focus({ preventScroll: true }), 450)
    return () => clearTimeout(t)
  }, [open])
  const review = status?.items?.review || 0
  const main = NAV.filter((n) => ['dashboard', 'review', 'categories', 'settings'].includes(n.key))
  const sub = NAV.filter((n) => ['history', 'insights', 'guides'].includes(n.key))
  const item = (n, i, small) => (
    <a key={n.key} ref={i === 0 ? first : undefined} href={`#/${n.key}`} onClick={onClose} tabIndex={open ? 0 : -1}
      className={`menu-item ${small ? 'small' : ''} ${page === n.key ? 'active' : ''}`} style={{ '--i': i, '--r': `${n.r}deg` }}>
      <span className="tip">{n.label}<small>{n.key === 'review' && review ? `${review} waiting` : n.note}</small></span>
      <Sticker name={n.key} />
    </a>
  )
  return (
    <div id="app-menu" className={`menu ${open ? 'open' : ''}`} aria-hidden={!open}>
      <nav className="menu-main" aria-label="Menu">{main.map((n, i) => item(n, i))}</nav>
      <div className="menu-sub">
        <div className="menu-sub-label">( or the rest of it )</div>
        <div className="menu-sub-row">
          {sub.map((n, i) => item(n, i + 4, true))}
          <button type="button" className="menu-item small" style={{ '--i': 7, '--r': '5deg' }} tabIndex={open ? 0 : -1}
            onClick={() => { onEngine(); onClose() }}>
            <span className="tip">{status?.running ? 'Stop engine' : 'Start engine'}<small>{status?.running ? 'running' : 'stopped'}</small></span>
            <Sticker name="power" />
          </button>
        </div>
      </div>
      <div className="menu-foot">
        <b>CLIPPED</b>
        <div className="menu-foot-links">
          <a href="#/guides" onClick={onClose}>Guides</a><i>·</i>
          <a href="https://github.com/ritviksajeev/clipped" target="_blank" rel="noreferrer">GitHub</a><i>·</i>
          <a href="https://evzero.org" target="_blank" rel="noreferrer">evzero.org</a>
        </div>
        <span className="menu-keys"><kbd>Ctrl</kbd> + <kbd>1</kbd>–<kbd>7</kbd> jump anywhere · <kbd>Esc</kbd> close</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- status bar

function StatusBar({ status }) {
  const now = useNow()
  const peak = useRef({})
  const state = engineState(status)
  const nu = status?.next_upload
  const left = nu ? Math.max(0, (new Date(nu.at).getTime() - now) / 1000) : null
  if (nu && left != null) peak.current[nu.item_id] = Math.max(peak.current[nu.item_id] || 0, left, 1)
  const progress = nu ? 1 - left / (peak.current[nu.item_id] || 1) : 0
  const q = status?.quota || {}
  const quotaPct = Math.min(100, ((q.used || 0) / (q.limit || 1)) * 100)
  const activity = Object.values(status?.activity || {}).find((a) => a && a !== 'idle')
  const C = 2 * Math.PI * 6
  return (
    <footer className="statusbar">
      <span className={`sb-state ${status?.running ? (state === 'paused' ? 'paused' : 'on') : ''}`}>
        <span className="led" />{STATE_LABEL[state] || state}
      </span>
      <span className="sb-activity">{status?.offline ? "Can't reach the engine" : activity || (status?.running ? 'Watching for clips' : 'Press start to go')}</span>
      <span className="sb-sep" />
      <span className="sb-next" title={nu ? `${fmtTime(nu.at)} · ${nu.reason}` : ''}>
        <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" className="track" /><circle cx="8" cy="8" r="6" className="fill"
          strokeDasharray={C} strokeDashoffset={C * (1 - progress)} /></svg>
        {nu ? (left > 0 ? <>Next upload <b>{fmtDuration(left)}</b></> : <>Upload <b>{status?.running ? 'now' : 'ready'}</b></>) : 'No upload queued'}
      </span>
      <span className="sb-quota" title={`YouTube API quota · resets ${fmtTime(q.resets_at)}`}>
        Quota <span className="sb-meter"><span style={{ width: `${Math.max(quotaPct, 2)}%` }} /></span>
        {(q.used || 0).toLocaleString()}/{(q.limit || 0).toLocaleString()}
      </span>
      <span className="sb-today">{status?.uploads_today ?? 0}/{status?.max_uploads_per_day ?? 0} today</span>
      <span className="sb-ver">v{status?.version || '-'}</span>
    </footer>
  )
}

// ---------------------------------------------------------------- app

export default function App() {
  const [route, setRoute] = useState(parseHash())
  const [status, setStatus] = useState(null)
  const [toasts, setToasts] = useState([])
  const [menuOpen, setMenuOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [native, setNative] = useState(hasNativeWindow())
  const contentRef = useRef(null)

  useEffect(() => {
    const ready = () => setNative(hasNativeWindow())
    window.addEventListener('pywebviewready', ready)
    return () => window.removeEventListener('pywebviewready', ready)
  }, [])
  useEffect(() => { document.documentElement.classList.toggle('native', native) }, [native])

  useEffect(() => {
    const onHash = () => {
      const next = parseHash()
      setRoute((prev) => {
        if (prev.page !== next.page || prev.sub !== next.sub) contentRef.current?.scrollTo({ top: 0 })
        return next
      })
      setMenuOpen(false)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') setMenuOpen(false)
      if ((e.ctrlKey || e.metaKey) && /^[1-7]$/.test(e.key)) {
        e.preventDefault()
        window.location.hash = `#/${NAV[Number(e.key) - 1].key}`
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  useEffect(() => { document.documentElement.classList.toggle('menu-open', menuOpen) }, [menuOpen])

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
  useEffect(() => { document.documentElement.classList.toggle('engine-on', !!status?.running) }, [status?.running])

  const notify = useCallback((message, kind = 'info') => {
    const id = Date.now() + Math.random()
    setToasts((list) => [...list.slice(-2), { id, message, kind }])
    setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), kind === 'error' ? 7000 : 3600)
  }, [])

  const toggleEngine = useCallback(async () => {
    if (busy) return
    setBusy(true)
    const wasRunning = !!status?.running
    try {
      await api.post(wasRunning ? '/api/engine/stop' : '/api/engine/start')
      await refreshStatus()
      notify(wasRunning ? 'Engine stopped' : 'Engine started. Looking for clips now.', wasRunning ? 'info' : 'ok')
    } catch (e) { notify(e.message, 'error') } finally { setBusy(false) }
  }, [busy, status?.running, refreshStatus, notify])

  const Page = PAGES[route.page]

  return (
    <AppContext.Provider value={{ status, refreshStatus, notify, route, toggleEngine, engineBusy: busy }}>
      <div className="app">
        <TitleBar status={status} page={route.page} menuOpen={menuOpen} onMenu={() => setMenuOpen((o) => !o)} native={native} />
        <div className="body">
          <Rail page={route.page} status={status} onEngine={toggleEngine} busy={busy} />
          <main className="content" ref={contentRef}>
            {status?.offline && <div className="banner error" style={{ marginBottom: 16 }}>Can't reach the clipped engine. Is the app still running?</div>}
            <div key={`${route.page}/${route.sub}`} className="page-enter">
              <Page />
            </div>
          </main>
          <Menu open={menuOpen} page={route.page} status={status} onClose={() => setMenuOpen(false)} onEngine={toggleEngine} />
        </div>
        <StatusBar status={status} />
        <div className="toasts" aria-live="polite">
          {toasts.map((t) => (
            <div key={t.id} className={`toast ${t.kind}`} role="status" onClick={() => setToasts((l) => l.filter((x) => x.id !== t.id))}>
              <span className="bar" />{t.message}
            </div>
          ))}
        </div>
      </div>
    </AppContext.Provider>
  )
}
