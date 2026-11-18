import React, { useEffect, useRef, useState } from 'react'
import { api, fmtDuration, fmtTime } from '../api.js'
import { StatusDot, useApp } from '../App.jsx'

function useCountdown(targetIso) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  if (!targetIso) return null
  return Math.max(0, (new Date(targetIso).getTime() - now) / 1000)
}

function Checklist({ status }) {
  const steps = [
    ['Twitch keys saved', status.twitch_configured, '#/settings'],
    ['YouTube connected', status.youtube_connected, '#/settings'],
    ['At least one category', (status.categories_count ?? 1) > 0, '#/categories'],
    ['ffmpeg available', status.ffmpeg, '#/guides/ffmpeg'],
  ]
  if (steps.every(([, ok]) => ok)) return null
  return (
    <section className="card">
      <h2>Finish setup</h2>
      <ol className="checklist">
        {steps.map(([label, ok, href]) => (
          <li key={label} className={ok ? 'done' : ''}>
            <span className="tick">{ok ? '✓' : '•'}</span>
            {ok ? label : <a href={href}>{label}</a>}
          </li>
        ))}
      </ol>
      <p className="muted small">New here? Start with the <a href="#/guides/quick-start">quick start guide</a>.</p>
    </section>
  )
}

function Logs() {
  const [lines, setLines] = useState([])
  const [follow, setFollow] = useState(true)
  const box = useRef(null)
  useEffect(() => {
    let es
    let poll
    let last = 0
    const push = (entries) => {
      if (!entries.length) return
      last = entries[entries.length - 1].seq
      setLines((prev) => {
        const seen = new Set(prev.map((l) => l.seq))
        return [...prev, ...entries.filter((e) => !seen.has(e.seq))].slice(-600)
      })
    }
    try {
      es = new EventSource('/api/logs/stream')
      es.onmessage = (ev) => push([JSON.parse(ev.data)])
      es.onerror = () => {
        es.close()
        poll = setInterval(async () => {
          try { push(await api.get(`/api/logs?after=${last}`)) } catch { /* offline */ }
        }, 3000)
      }
    } catch {
      /* EventSource unsupported */
    }
    return () => { es && es.close(); poll && clearInterval(poll) }
  }, [])
  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight
  }, [lines, follow])
  return (
    <section className="card logs-card">
      <div className="row between">
        <h2>Live log</h2>
        <label className="check small"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> follow</label>
      </div>
      <div className="logs" ref={box} onScroll={(e) => {
        const el = e.currentTarget
        setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 30)
      }}>
        {lines.length === 0 && <div className="muted">Nothing yet. Press Start.</div>}
        {lines.map((l) => (
          <div key={l.seq} className={`log ${l.level.toLowerCase()}`}>
            <span className="log-time">{new Date(l.ts * 1000).toLocaleTimeString()}</span>
            <span className="log-msg">{l.message}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

export default function Dashboard() {
  const { status, refreshStatus, notify } = useApp()
  const [busy, setBusy] = useState(false)
  const [cats, setCats] = useState(null)
  const countdown = useCountdown(status?.next_upload?.at)

  useEffect(() => { api.get('/api/categories').then(setCats).catch(() => setCats([])) }, [])

  if (!status || status.offline && !status.state) return <div className="muted">Connecting to the engine…</div>
  const running = status.running
  const toggle = async () => {
    setBusy(true)
    try {
      await api.post(running ? '/api/engine/stop' : '/api/engine/start')
      await refreshStatus()
      notify(running ? 'Stopped' : 'Started. ClipPilot is now looking for clips.')
    } catch (e) {
      notify(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }
  const pause = async (hours) => {
    const until = hours ? new Date(Date.now() + hours * 3600 * 1000).toISOString() : null
    await api.post('/api/engine/pause', { until })
    refreshStatus()
    notify(hours ? `Uploads paused for ${hours}h` : 'Uploads resumed')
  }
  const items = status.items || {}
  const q = status.quota || {}
  const nu = status.next_upload
  const enriched = { ...status, categories_count: cats ? cats.length : 1 }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p className="muted">Mode: <strong>{status.mode === 'auto' ? 'Auto' : 'Manual approval'}</strong>
            {' · '}<a href="#/settings">change</a></p>
        </div>
      </header>

      {status.auth_problem && <div className="banner error">{status.auth_problem} <a href="#/settings">Reconnect YouTube</a></div>}
      {status.quota_paused_until && <div className="banner warn">YouTube API quota used up for today. Uploads resume at {fmtTime(status.quota_paused_until)}.</div>}
      {!status.secret_storage_is_os && <div className="banner warn small">No OS keychain found, so your keys are stored in a file only your user account can read. <a href="#/guides/troubleshooting">Details</a></div>}

      <Checklist status={enriched} />

      <section className="hero card">
        <button className={`power ${running ? 'on' : 'off'}`} onClick={toggle} disabled={busy}
          aria-pressed={running}>
          <span className="power-icon">{running ? '■' : '▶'}</span>
          <span>{running ? 'Stop' : 'Start'}</span>
        </button>
        <div className="hero-info">
          <StatusDot status={status} large />
          <div className="activity">
            {Object.entries(status.activity || {}).filter(([, a]) => a !== 'idle').map(([k, a]) => (
              <div key={k}><span className="pill">{k === 'net' ? 'network' : 'render'}</span> {a}</div>
            ))}
            {running && Object.values(status.activity || {}).every((a) => a === 'idle') &&
              <div className="muted">Waiting for the next job…</div>}
          </div>
          <div className="next-upload">
            <div className="label">Next upload</div>
            {nu ? (
              <>
                <div className="countdown">{countdown > 0 ? fmtDuration(countdown) : 'due now'}</div>
                <div className="muted small">{fmtTime(nu.at)} · {nu.reason} · “{nu.title?.slice(0, 60)}”</div>
              </>
            ) : (
              <div className="muted">{status.auth_problem ? 'Uploads are on hold until YouTube is reconnected'
                : status.youtube_connected ? 'Nothing approved or ready yet' : 'Connect YouTube to upload'}</div>
            )}
          </div>
          <div className="row gap">
            {status.paused_until
              ? <button className="btn" onClick={() => pause(0)}>Resume uploads (paused until {fmtTime(status.paused_until)})</button>
              : <>
                <button className="btn ghost small" onClick={() => pause(1)}>Pause 1h</button>
                <button className="btn ghost small" onClick={() => pause(24)}>Pause 24h</button>
              </>}
          </div>
        </div>
      </section>

      <section className="stats-grid">
        <a className="stat card" href="#/review"><div className="stat-num">{items.review || 0}</div><div className="muted">waiting for review</div></a>
        <div className="stat card"><div className="stat-num">{(items.approved || 0) + (items.ready || 0)}</div><div className="muted">approved / ready</div></div>
        <div className="stat card"><div className="stat-num">{status.uploads_today}/{status.max_uploads_per_day}</div><div className="muted">uploaded today</div></div>
        <a className="stat card" href="#/history"><div className="stat-num">{items.uploaded || 0}</div><div className="muted">uploaded total</div></a>
        <div className="stat card quota">
          <div className="row between"><span className="muted">YouTube API quota</span><span className="small muted">resets {fmtTime(q.resets_at)}</span></div>
          <div className="meter"><span style={{ width: `${Math.min(100, (q.used / (q.limit || 1)) * 100)}%` }} /></div>
          <div className="small">{q.used?.toLocaleString()} / {q.limit?.toLocaleString()} units · ~{q.uploads_left} upload(s) left</div>
        </div>
        {items.processing > 0 && <div className="stat card"><div className="stat-num">{items.processing}</div><div className="muted">rendering</div></div>}
        {items.failed > 0 && <a className="stat card" href="#/review?tab=failed"><div className="stat-num warn-text">{items.failed}</div><div className="muted">failed</div></a>}
      </section>

      {status.last_error && <div className="banner warn small">Last error: {status.last_error}</div>}
      <Logs />
    </div>
  )
}
