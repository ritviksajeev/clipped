import React, { useEffect, useRef, useState } from 'react'
import { api, fmtNum, fmtTime } from '../api.js'
import { engineState, useApp } from '../App.jsx'
import { ActivityChart, Ring, Spark } from '../components/charts.jsx'
import { Count, Loading } from '../components/ui.jsx'
import { useNow } from '../fx.js'
import { Sticker } from '../stickers.jsx'
import { BoxArt } from './Categories.jsx'

// The engine state, written like a burned-in caption: the word that matters
// pops in the highlight colour, the way clipped captions a Short.
const CAPTION = {
  stopped: ['Engine', 'off'],
  idle: ['Watching', 'for clips'],
  working: ['Making', 'Shorts'],
  paused: ['Uploads', 'paused'],
  offline: ['Engine', 'offline'],
}

function Clock({ seconds }) {
  if (seconds == null) return null
  if (seconds <= 0) return <span className="clock">now</span>
  const s = Math.round(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const pad = (n) => String(n).padStart(2, '0')
  return <span className="clock">{h > 0 && <>{h}<span className="u">h</span></>}{pad(m)}<span className="u">m</span>{pad(s % 60)}<span className="u">s</span></span>
}

function Setup({ status, cats }) {
  const steps = [
    ['Twitch keys', status.twitch_configured, '#/settings/connections'],
    ['A game to watch', (cats?.length ?? 1) > 0, '#/categories'],
    ['YouTube or Instagram (or just download)', status.youtube_connected || status.instagram_connected || status.download_only, '#/settings/connections'],
  ]
  if (steps.every(([, ok]) => ok)) return null
  return (
    <section className="setup-strip">
      <span className="label">Finish setup</span>
      {steps.map(([label, ok, href]) => (
        <a key={label} href={href} className={`setup-step ${ok ? 'done' : ''}`}><span className="tick">{ok ? '✓' : '•'}</span>{label}</a>
      ))}
      <a className="ulink" href="#/guides/quick-start">Quick start</a>
    </section>
  )
}

function Logs() {
  const [lines, setLines] = useState([])
  const [open, setOpen] = useState(false)
  const box = useRef(null)
  useEffect(() => {
    let es, poll, last = 0
    const push = (entries) => {
      if (!entries.length) return
      last = entries[entries.length - 1].seq
      setLines((prev) => {
        const seen = new Set(prev.map((l) => l.seq))
        return [...prev, ...entries.filter((e) => !seen.has(e.seq))].slice(-400)
      })
    }
    try {
      es = new EventSource('/api/logs/stream')
      es.onmessage = (ev) => push([JSON.parse(ev.data)])
      es.onerror = () => {
        es.close()
        poll = setInterval(async () => { try { push(await api.get(`/api/logs?after=${last}`)) } catch { /* offline */ } }, 3000)
      }
    } catch { /* no EventSource */ }
    return () => { es && es.close(); poll && clearInterval(poll) }
  }, [])
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight }, [lines, open])
  const shown = open ? lines : lines.slice(-4)
  return (
    <section className={`card log-card ${open ? 'open' : ''}`}>
      <div className="card-head">
        <h2>Activity</h2>
        <button className="linklike label" onClick={() => setOpen((o) => !o)}>{open ? 'Less' : 'Full log'}</button>
      </div>
      <div className="logs" ref={box}>
        {lines.length === 0 && <div className="faint small">Nothing yet. Start the engine.</div>}
        {shown.map((l) => (
          <div key={l.seq} className={`log ${l.level.toLowerCase()}`}>
            <span className="log-time">{new Date(l.ts * 1000).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit' })}</span>
            <span className="log-msg">{l.message}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

export default function Dashboard() {
  const { status, refreshStatus, notify, toggleEngine, engineBusy } = useApp()
  const [cats, setCats] = useState(null)
  const [act, setAct] = useState(null)
  const [pressed, setPressed] = useState(0)
  const now = useNow()

  useEffect(() => { api.get('/api/categories').then(setCats).catch(() => setCats([])) }, [])
  useEffect(() => {
    const load = () => api.get('/api/activity?days=14').then(setAct).catch(() => {})
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [])

  if (!status || (status.offline && !status.state)) return <Loading label="Connecting to the engine" />
  const running = status.running
  const state = engineState(status)
  const [word, hl] = CAPTION[state] || CAPTION.stopped
  const pause = async (hours) => {
    const until = hours ? new Date(Date.now() + hours * 3600 * 1000).toISOString() : null
    await api.post('/api/engine/pause', { until })
    refreshStatus()
    notify(hours ? `Uploads paused for ${hours}h` : 'Uploads resumed')
  }
  const items = status.items || {}
  const q = status.quota || {}
  const nu = status.next_upload
  const left = nu ? Math.max(0, (new Date(nu.at).getTime() - now) / 1000) : null
  const job = Object.values(status.activity || {}).find((a) => a && a !== 'idle')
  const enabled = (cats || []).filter((c) => c.enabled)
  const series = (k) => act?.days?.map((d) => d[k]) || []

  return (
    <div className="page dash">
      {status.auth_problem && <div className="banner error">{status.auth_problem} <a href="#/settings/connections">Reconnect</a></div>}
      {status.quota_paused_until && <div className="banner warn">YouTube's upload quota is used up for today. Uploads resume at {fmtTime(status.quota_paused_until)}.</div>}
      <Setup status={status} cats={cats} />

      <section className={`dash-hero ${running ? 'on' : ''} ${state === 'paused' ? 'paused' : ''}`}>
        <button className="engine-btn" key={pressed} onClick={() => { setPressed((p) => p + 1); toggleEngine() }} disabled={engineBusy}
          aria-pressed={running} aria-label={running ? 'Stop the engine' : 'Start the engine'}>
          <span className="engine-orbit" aria-hidden="true" />
          <Sticker name="power" />
        </button>
        <div className="dash-hero-text">
          <div className="caption-state" key={state}><span>{word}</span> <span className="hl">{hl}</span></div>
          <p className="dash-now">{job || (running ? 'Waiting for the next job' : 'Press the switch to start finding clips')}</p>
        </div>
        <div className="dash-next">
          <span className="label">Next upload</span>
          {nu ? <><Clock seconds={left} /><span className="faint small ellipsis" title={nu.title}>{nu.title}</span></>
            : <span className="muted small">{status.youtube_connected || status.instagram_connected ? 'Nothing approved yet' : 'Not connected · download from Review'}</span>}
          {status.paused_until
            ? <button className="linklike small" onClick={() => pause(0)}>Resume (paused until {fmtTime(status.paused_until)})</button>
            : <span className="dash-pause"><button className="linklike small" onClick={() => pause(1)}>Pause 1h</button> · <button className="linklike small" onClick={() => pause(24)}>24h</button></span>}
        </div>
      </section>

      <section className="tiles">
        <a className="tile" href="#/review"><span className="label">To review</span><b><Count value={items.review || 0} /></b><Spark values={series('made')} /></a>
        <a className="tile" href="#/review?tab=scheduled"><span className="label">Scheduled</span><b><Count value={(items.approved || 0) + (items.ready || 0)} /></b></a>
        <a className="tile" href="#/history"><span className="label">Uploaded today</span><b><Count value={status.uploads_today || 0} /><small>/{status.max_uploads_per_day}</small></b><Spark values={series('uploaded')} /></a>
        <a className="tile" href="#/insights"><span className="label">Views · 14 days</span><b><Count value={act?.totals?.views || 0} format={(v) => fmtNum(Math.round(v))} /></b><Spark values={series('views')} /></a>
      </section>

      <div className="dash-grid">
        <section className="card chart-card">
          <div className="card-head"><h2>Last 14 days</h2><span className="label">{act ? `${act.totals.made} made · ${act.totals.uploaded} uploaded` : ''}</span></div>
          {act ? <ActivityChart days={act.days} /> : <Loading />}
        </section>
        <div className="dash-side">
          <section className="card ring-card">
            <Ring value={q.used || 0} max={q.limit || 1} label={`${q.uploads_left ?? 0}`} sub="uploads left" />
            <div>
              <h2>YouTube quota</h2>
              <p className="faint small">{(q.used || 0).toLocaleString()} of {(q.limit || 0).toLocaleString()} units · resets {fmtTime(q.resets_at)}</p>
            </div>
          </section>
          <section className="card watching">
            <div className="card-head"><h2>Watching</h2><a className="ulink" href="#/categories">Edit</a></div>
            {cats === null ? <Loading /> : enabled.length === 0
              ? <p className="muted small">No games yet. <a className="link" href="#/categories">Pick some</a>.</p>
              : <div className="mini-cats">{enabled.slice(0, 6).map((c, i) => (
                <a key={c.id} href="#/categories" className="mini-cat" title={c.name}><BoxArt src={c.box_art_url} i={i} size="md" /></a>
              ))}</div>}
          </section>
        </div>
      </div>

      {items.failed > 0 && <a className="banner warn small" href="#/review?tab=failed">{items.failed} Short{items.failed === 1 ? '' : 's'} failed. Open Review to retry.</a>}
      <Logs />
    </div>
  )
}
