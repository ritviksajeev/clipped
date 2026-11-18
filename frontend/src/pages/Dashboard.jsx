import React, { useEffect, useRef, useState } from 'react'
import { api, fmtTime } from '../api.js'
import { engineState, useApp } from '../App.jsx'
import { Count, Kicker, Marquee, PageHead, Warp } from '../fx/components.jsx'

function useCountdown(targetIso) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  if (!targetIso) return null
  return Math.max(0, (new Date(targetIso).getTime() - now) / 1000)
}

function Clock({ seconds }) {
  if (seconds == null) return null
  if (seconds <= 0) return <span className="countdown">due <span className="unit">now</span></span>
  const s = Math.round(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const pad = (n) => String(n).padStart(2, '0')
  return (
    <span className="countdown">
      {h > 0 && <>{h}<span className="unit">h</span></>}
      {pad(m)}<span className="unit">m</span>{pad(sec)}<span className="unit">s</span>
    </span>
  )
}

const WORDS = {
  stopped: ['Stopped', 'for now.'],
  idle: ['Running', 'quietly.'],
  working: ['Working', 'on it.'],
  paused: ['Paused', 'on purpose.'],
  offline: ['Offline', 'oops.'],
}

function Checklist({ status, cats }) {
  const steps = [
    ['Twitch keys saved', status.twitch_configured, '#/settings/connections'],
    ['YouTube connected', status.youtube_connected, '#/settings/connections'],
    ['At least one category', (cats?.length ?? 1) > 0, '#/categories'],
    ['ffmpeg available', status.ffmpeg, '#/guides/ffmpeg'],
  ]
  if (steps.every(([, ok]) => ok)) return null
  const done = steps.filter(([, ok]) => ok).length
  return (
    <section className="card glow reveal">
      <div className="card-head">
        <h2>Finish setup</h2>
        <span className="chip accent">{done} / {steps.length} done</span>
      </div>
      <ol className="checklist">
        {steps.map(([label, ok, href], i) => (
          <li key={label} className={ok ? 'done' : ''}>
            <span className="tick">{ok ? '✓' : String(i + 1).padStart(2, '0')}</span>
            {ok ? label : <a className="link" href={href}>{label}</a>}
          </li>
        ))}
      </ol>
      <p className="field-hint" style={{ marginTop: 14 }}>New here? Start with the <a className="link" href="#/guides/quick-start">quick start guide</a>.</p>
    </section>
  )
}

function Logs() {
  const [lines, setLines] = useState([])
  const [follow, setFollow] = useState(true)
  const box = useRef(null)
  useEffect(() => {
    let es, poll, last = 0
    const push = (entries) => {
      if (!entries.length) return
      last = entries[entries.length - 1].seq
      setLines((prev) => {
        const seen = new Set(prev.map((l) => l.seq))
        return [...prev, ...entries.filter((e) => !seen.has(e.seq))].slice(-500)
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
    } catch { /* no EventSource */ }
    return () => { es && es.close(); poll && clearInterval(poll) }
  }, [])
  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight
  }, [lines, follow])
  return (
    <section className="card glow reveal">
      <div className="card-head">
        <h2>Live log</h2>
        <label className="check small"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> <span className="label">follow</span></label>
      </div>
      <div className="logs" ref={box} data-lenis-prevent="" onScroll={(e) => {
        const el = e.currentTarget
        setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 30)
      }}>
        {lines.length === 0 && <div className="faint">Nothing yet. Press start.</div>}
        {lines.map((l) => (
          <div key={l.seq} className={`log ${l.level.toLowerCase()}`}>
            <span className="log-time">{new Date(l.ts * 1000).toLocaleTimeString([], { hour12: false })}</span>
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
  const [burst, setBurst] = useState(0)
  const countdown = useCountdown(status?.next_upload?.at)

  useEffect(() => { api.get('/api/categories').then(setCats).catch(() => setCats([])) }, [])

  if (!status || (status.offline && !status.state)) return <div className="faint label">Connecting to the engine…</div>
  const running = status.running
  const state = engineState(status)
  const [word, accent] = WORDS[state] || WORDS.stopped
  const toggle = async () => {
    setBusy(true)
    try {
      await api.post(running ? '/api/engine/stop' : '/api/engine/start')
      if (!running) setBurst((b) => b + 1)
      await refreshStatus()
      notify(running ? 'Stopped' : 'Started. Looking for clips now.')
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
  const activity = Object.entries(status.activity || {}).filter(([, a]) => a !== 'idle')
  const quotaPct = Math.min(100, (q.used / (q.limit || 1)) * 100)

  return (
    <div className="page">
      <PageHead crumb="dashboard" meta={`v${status.version || ''} · ${status.mode === 'auto' ? 'auto mode' : 'manual approval'}`}
        text="Clip" accent="control."
        lead={<>Mode: <b>{status.mode === 'auto' ? 'Auto' : 'Manual approval'}</b>. {status.mode === 'auto'
          ? 'clipped picks, renders and uploads on its own schedule.'
          : 'Nothing goes up until you approve it.'} <a className="link" href="#/settings/mode">Change</a></>} />

      {status.auth_problem && <div className="banner error">{status.auth_problem} <a href="#/settings/connections">Reconnect YouTube</a></div>}
      {status.quota_paused_until && <div className="banner warn">YouTube API quota is used up for today. Uploads resume at {fmtTime(status.quota_paused_until)}.</div>}
      {!status.secret_storage_is_os && <div className="banner warn small">No OS keychain found, so your keys are stored in a file only your user account can read. <a href="#/guides/troubleshooting">Details</a></div>}

      <Checklist status={status} cats={cats} />

      <section className="hero-panel glow reveal">
        <Warp speed={running ? 0.0034 : 0.0009} burst={burst} />
        <div className={`orb-wrap ${running ? 'on' : ''}`}>
          <div className="orb-rings" aria-hidden="true"><i /><i /><i /></div>
          <button className="orb" onClick={toggle} disabled={busy} aria-pressed={running} data-magnetic="0.12"
            data-cursor-label={running ? 'Stop' : 'Go'}>
            <svg className="orb-icon" viewBox="0 0 24 24" aria-hidden="true">
              {running ? <rect x="6" y="6" width="12" height="12" rx="2" /> : <path d="M8 5.5v13l11-6.5z" />}
            </svg>
            {running ? 'Stop' : 'Start'}
            <small>{running ? 'engine on' : 'engine off'}</small>
          </button>
        </div>
        <div className="hero-info">
          <div className="state-word" key={state}>{word} <span className="accent">{accent}</span></div>
          <div className="activity">
            {activity.map(([k, a]) => (
              <div key={k + a}><span className="chip accent">{k === 'net' ? 'network' : 'render'}</span> {a}</div>
            ))}
            {running && !activity.length && <div className="faint">Waiting for the next job…</div>}
          </div>
          <div>
            <div className="next-label">Next upload</div>
            {nu ? (
              <>
                <Clock seconds={countdown} />
                <div className="next-meta">{fmtTime(nu.at)} · {nu.reason} · “{nu.title?.slice(0, 64)}”</div>
              </>
            ) : (
              <div className="next-meta" style={{ marginTop: 6 }}>{status.auth_problem ? 'On hold until YouTube is reconnected'
                : status.youtube_connected ? 'Nothing approved or ready yet' : 'Connect YouTube to upload'}</div>
            )}
          </div>
          <div className="row">
            {status.paused_until
              ? <button className="btn small" onClick={() => pause(0)}>Resume uploads · paused until {fmtTime(status.paused_until)}</button>
              : <>
                <button className="btn small ghost" onClick={() => pause(1)}>Pause 1h</button>
                <button className="btn small ghost" onClick={() => pause(24)}>Pause 24h</button>
              </>}
          </div>
        </div>
      </section>

      <Kicker idx={1} name="Numbers" meta={`${status.uploads_today}/${status.max_uploads_per_day} today`} />
      <section className="stat-grid">
        <a className="stat glow reveal" href="#/review">
          <span className="stat-top">Waiting for review <span className="arrow">↗</span></span>
          <span className="stat-num"><Count value={items.review || 0} /></span>
        </a>
        <div className="stat glow reveal d1">
          <span className="stat-top">Approved · ready</span>
          <span className="stat-num"><Count value={(items.approved || 0) + (items.ready || 0)} /></span>
        </div>
        <div className="stat glow reveal d2">
          <span className="stat-top">Uploaded today</span>
          <span className="stat-num"><Count value={status.uploads_today} /><small> / {status.max_uploads_per_day}</small></span>
        </div>
        <a className="stat glow reveal d3" href="#/history">
          <span className="stat-top">Uploaded total <span className="arrow">↗</span></span>
          <span className="stat-num"><Count value={items.uploaded || 0} /></span>
        </a>
        {items.processing > 0 && (
          <div className="stat glow reveal d4">
            <span className="stat-top">Rendering</span>
            <span className="stat-num"><Count value={items.processing} /></span>
          </div>
        )}
        {items.failed > 0 && (
          <a className="stat glow reveal d4" href="#/review?tab=failed">
            <span className="stat-top">Failed <span className="arrow">↗</span></span>
            <span className="stat-num warn-text"><Count value={items.failed} /></span>
          </a>
        )}
        <div className="stat wide glow reveal d4">
          <span className="stat-top">YouTube API quota <span>resets {fmtTime(q.resets_at)}</span></span>
          <div className="stack" style={{ gap: 10 }}>
            <span className="stat-num" style={{ fontSize: 'clamp(30px, 3vw, 44px)' }}>
              <Count value={q.used || 0} /><small> / {(q.limit || 0).toLocaleString()} units</small>
            </span>
            <div className="meter"><span style={{ width: `${Math.max(quotaPct, 1.5)}%` }} /></div>
            <span className="field-hint">About {q.uploads_left} upload(s) left today</span>
          </div>
        </div>
      </section>

      {cats && cats.length > 0 && (
        <section className="reveal" style={{ margin: '10px 0' }}>
          <Marquee items={cats.map((c) => c.name)} />
        </section>
      )}

      {status.last_error && <div className="banner warn small">Last error: {status.last_error}</div>}
      <Kicker idx={2} name="Live log" meta="streams from the engine" />
      <Logs />
    </div>
  )
}
