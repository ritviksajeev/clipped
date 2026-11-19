import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { api, hasNativeWindow, nativeApi, openPage, windowControl } from './api.js'
import { Sticker } from './stickers.jsx'
import Splash from './shell/Splash.jsx'
import Gate from './shell/Gate.jsx'
import Home from './shell/Home.jsx'
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
  { key: 'settings', label: 'Settings', note: 'tune it', r: 4 },
  { key: 'history', label: 'History', note: 'uploads', r: 6 },
  { key: 'insights', label: 'Insights', note: 'what works', r: -5 },
  { key: 'guides', label: 'Guides', note: 'set up', r: -3 },
]
const PAGES = { dashboard: Dashboard, review: Review, history: History, insights: Insights,
  categories: Categories, settings: Settings, guides: Guides }

export const AppContext = createContext(null)
export const useApp = () => useContext(AppContext)

// '#/' (or nothing) is home, the sticker menu. Everything else is a page.
function parseHash() {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const [path, query = ''] = raw.split('?')
  const [page = '', ...rest] = path.split('/')
  return { page: PAGES[page] ? page : 'home', sub: rest.join('/'), params: new URLSearchParams(query) }
}

export function engineState(status) {
  if (!status || status.offline) return 'offline'
  return status.state || 'stopped'
}
export const STATE_LABEL = { stopped: 'Stopped', idle: 'Running', working: 'Working', paused: 'Paused', offline: 'Offline' }

// ---------------------------------------------------------------- top bar

function Icon({ d, size = 10 }) {
  return <svg width={size} height={size} viewBox="0 0 10 10" fill="none" aria-hidden="true">{d}</svg>
}

// One slim bar, part of the window rather than a header on top of it. At home it is
// just the mark and the window buttons; on a page it adds where you are and a way back.
function TopBar({ page, status, phase, onEngine, engineBusy, native, maxed, setMaxed, license }) {
  const state = engineState(status)
  const nav = NAV.find((n) => n.key === page)
  const atHome = phase !== 'app' || page === 'home'
  const drag = native && !maxed ? 'pywebview-drag-region' : ''
  return (
    <header className={`titlebar ${atHome ? 'at-home' : ''} ${drag}`} onDoubleClick={(e) => {
      if (native && (e.target === e.currentTarget || e.target.classList.contains('tb-space'))) {
        windowControl('toggle_maximize'); setMaxed((m) => !m)
      }
    }}>
      {phase === 'app' && !atHome ? (
        <a href="#/" className="tb-home" aria-label="Back to the menu" title="Menu (Esc)">
          <span className="tb-back" aria-hidden="true">←</span>
          <span className="tb-stk"><Sticker name={page} /></span>
          <span className="tb-title">{nav?.label}</span>
        </a>
      ) : (
        <span className={`tb-brand ${drag}`}>
          <span className="tb-stk"><Sticker name="clipped" /></span>
          <span className="tb-word">clipped<i /></span>
        </span>
      )}
      <span className={`tb-space ${drag}`} />
      {phase === 'app' && license?.tier === 'free' && (
        <a className="plan-chip" href={license.buy_url} title="Free day · Shorts carry a watermark. Pro removes it."
          onClick={(e) => { e.preventDefault(); openPage(license.buy_url) }}>
          Free · {license.license?.hours_left ?? 0}h left
        </a>
      )}
      {phase === 'app' && status && !status.offline && (
        <button type="button" className={`state-pill ${status.running ? (state === 'paused' ? 'paused' : 'on') : 'off'}`}
          onClick={onEngine} disabled={engineBusy} title={status.running ? 'Stop the engine' : 'Start the engine'}>
          <span className="led" /><span>{STATE_LABEL[state] || state}</span>
        </button>
      )}
      {phase === 'app' && !atHome && (
        <a className="menu-btn" href="#/" aria-label="Menu">
          <span>Menu</span><span className="menu-btn-dots" aria-hidden="true"><i /><i /><i /><i /></span>
        </a>
      )}
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

// ---------------------------------------------------------------- edge resizing (native window)

// A frameless window has no OS border to grab, so the right edge, bottom edge
// and corner resize it through the native bridge.
function ResizeHandles() {
  const start = (edge) => (e) => {
    const api = nativeApi()
    if (!api?.resize_window || e.button !== 0) return
    e.preventDefault()
    const el = e.currentTarget
    el.setPointerCapture(e.pointerId)
    const from = { x: e.screenX, y: e.screenY, w: window.innerWidth, h: window.innerHeight }
    let want = null
    let busy = false
    let frame = 0
    const send = async () => {
      frame = 0
      if (busy || !want) return
      const next = want
      want = null
      busy = true
      try { await api.resize_window(next.w, next.h) } finally { busy = false; if (want) frame = requestAnimationFrame(send) }
    }
    const move = (ev) => {
      want = {
        w: edge === 'bottom' ? from.w : Math.round(from.w + ev.screenX - from.x),
        h: edge === 'right' ? from.h : Math.round(from.h + ev.screenY - from.y),
      }
      if (!frame) frame = requestAnimationFrame(send)
    }
    const up = () => {
      el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerup', up)
      el.removeEventListener('pointercancel', up)
      document.documentElement.classList.remove('resizing')
    }
    document.documentElement.classList.add('resizing')
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerup', up)
    el.addEventListener('pointercancel', up)
  }
  return (
    <>
      <div className="rz rz-right" onPointerDown={start('right')} aria-hidden="true" />
      <div className="rz rz-bottom" onPointerDown={start('bottom')} aria-hidden="true" />
      <div className="rz rz-corner" onPointerDown={start('corner')} aria-hidden="true" />
    </>
  )
}

// ---------------------------------------------------------------- app

export default function App() {
  const [phase, setPhase] = useState('splash') // splash → gate (no licence) → app
  const [license, setLicense] = useState(null)
  const [route, setRoute] = useState(parseHash())
  const [status, setStatus] = useState(null)
  const [toasts, setToasts] = useState([])
  const [busy, setBusy] = useState(false)
  const [native, setNative] = useState(hasNativeWindow())
  const [maxed, setMaxed] = useState(false)
  const contentRef = useRef(null)

  useEffect(() => {
    const ready = async () => {
      setNative(hasNativeWindow())
      try { const st = await nativeApi()?.window_state?.(); if (st) setMaxed(!!st.maximized) } catch { /* older bridge */ }
    }
    if (hasNativeWindow()) ready()
    window.addEventListener('pywebviewready', ready)
    return () => window.removeEventListener('pywebviewready', ready)
  }, [])
  useEffect(() => { document.documentElement.classList.toggle('native', native) }, [native])

  // The licence decides where the splash leads. Asked once at launch, and again
  // whenever the engine answers 402 (a monthly key ran out while the app was open).
  const checkLicense = useCallback(async () => {
    try { setLicense(await api.get('/api/license')) } catch { setLicense({ licensed: false, problem: "Can't reach the clipped engine.", offline: true }) }
  }, [])
  useEffect(() => { checkLicense() }, [checkLicense])
  useEffect(() => {
    if (phase !== 'app') return
    const t = setInterval(checkLicense, 5 * 60 * 1000) // hours left on a free day, Pro re-checks
    return () => clearInterval(t)
  }, [phase, checkLicense])
  useEffect(() => {
    const locked = () => { checkLicense(); setPhase((p) => (p === 'app' ? 'gate' : p)) }
    window.addEventListener('clipped:license', locked)
    return () => window.removeEventListener('clipped:license', locked)
  }, [checkLicense])
  const afterSplash = useCallback(() => setPhase((p) => (p === 'splash' ? (license?.licensed ? 'app' : 'gate') : p)), [license])
  const unlocked = useCallback((r) => { setLicense(r); setPhase('app'); window.location.hash = '#/' }, [])

  useEffect(() => {
    const onHash = () => {
      const next = parseHash()
      setRoute((prev) => {
        if (prev.page !== next.page || prev.sub !== next.sub) contentRef.current?.scrollTo({ top: 0 })
        return next
      })
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    const onKey = (e) => {
      if (phase !== 'app') return
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '')
      if (e.key === 'Escape' && !typing && !document.querySelector('.modal-backdrop')) window.location.hash = '#/'
      if ((e.ctrlKey || e.metaKey) && /^[1-7]$/.test(e.key)) {
        e.preventDefault()
        window.location.hash = `#/${NAV[Number(e.key) - 1].key}`
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [phase])

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await api.get('/api/status'))
    } catch (e) {
      if (e.status === 402) return // the licence handler takes it from here
      setStatus((s) => (s ? { ...s, offline: true } : { offline: true }))
    }
  }, [])
  useEffect(() => {
    if (phase !== 'app') return
    refreshStatus()
    const t = setInterval(refreshStatus, 3000)
    return () => clearInterval(t)
  }, [phase, refreshStatus])
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
    <AppContext.Provider value={{ status, refreshStatus, notify, route, toggleEngine, engineBusy: busy, license, checkLicense }}>
      <div className={`app phase-${phase} ${route.page === 'home' ? 'is-home' : 'is-page'}`}>
        <TopBar page={route.page} status={status} phase={phase} onEngine={toggleEngine} engineBusy={busy} license={license}
          native={native} maxed={maxed} setMaxed={setMaxed} />
        <main className="content" ref={contentRef}>
          {phase === 'gate' && <Gate license={license} onUnlocked={unlocked} />}
          {phase === 'app' && (
            <div key={`${route.page}/${route.sub}`} className={route.page === 'home' ? 'home-enter' : 'page-enter'}>
              {route.page === 'home'
                ? <Home nav={NAV} status={status} onEngine={toggleEngine} engineBusy={busy} />
                : <div className="page-wrap"><Page /></div>}
            </div>
          )}
        </main>
        {phase === 'splash' && <Splash ready={!!license} onDone={afterSplash} />}
        <div className="toasts" aria-live="polite">
          {toasts.map((t) => (
            <div key={t.id} className={`toast ${t.kind}`} role="status" onClick={() => setToasts((l) => l.filter((x) => x.id !== t.id))}>
              <span className="bar" />{t.message}
            </div>
          ))}
        </div>
        {native && !maxed && <ResizeHandles />}
      </div>
    </AppContext.Provider>
  )
}
