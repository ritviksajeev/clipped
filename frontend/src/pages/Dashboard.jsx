import React, { useEffect, useRef, useState } from 'react'
import { api, fmtTime } from '../api.js'
import { engineState, useApp } from '../App.jsx'
import { Count, Kicker, Loading, PageHead } from '../components/ui.jsx'
import { useNow } from '../fx.js'
import { Sticker } from '../stickers.jsx'
import { BoxArt } from './Categories.jsx'

// The engine state, written like a burned-in caption: the word that matters
// pops in the highlight colour, the way clipped captions a Short.
const CAPTION = {
  stopped: ['Engine', 'stopped'],
  idle: ['Engine', 'running'],
  working: ['Making', 'shorts'],
  paused: ['Uploads', 'paused'],
  offline: ['Engine', 'offline'],
}

function Clock({ seconds }) {
  if (seconds == null) return null
  if (seconds <= 0) return <span className="clock">due <span className="u">now</span></span>
  const s = Math.round(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const pad = (n) => String(n).padStart(2, '0')
  return (
    <span className="clock">
      {h > 0 && <>{h}<span className="u">h</span></>}{pad(m)}<span className="u">m</span>{pad(sec)}<span className="u">s</span>
    </span>
  )
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
    <section className="card glow setup">
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
      <p className="field-hint">New here? Start with the <a className="link" href="#/guides/quick-start">quick start guide</a>.</p>
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
    <section className="card glow log-card">
      <div className="card-head">
        <h2>Live log</h2>
        <label className="check small"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> <span className="label">follow</span></label>
      </div>
      <div className="logs" ref={box} onScroll={(e) => {
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
  const { status, refreshStatus, notify, toggleEngine, engineBusy } = useApp()
  const [cats, setCats] = useState(null)
  const [pressed, setPressed] = useState(0)
  const now = useNow()

  useEffect(() => { api.get('/api/categories').then(setCats).catch(() => setCats([])) }, [])

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
  const activity = Object.entries(status.activity || {}).filter(([, a]) => a !== 'idle')
  const quotaPct = Math.min(100, ((q.used || 0) / (q.limit || 1)) * 100)
  const enabled = (cats || []).filter((c) => c.enabled)

  return (
    <div className="page">
      <PageHead idx={1} crumb="dashboard" title="Clip" accent="control."
        lead={<>Mode: <b>{status.mode === 'auto' ? 'Auto' : 'Manual approval'}</b>. {status.mode === 'auto'
          ? 'clipped picks, renders and uploads on its own schedule.'
          : 'Nothing goes up until you approve it.'} <a className="link" href="#/settings/mode">Change</a></>} />

      {status.auth_problem && <div className="banner error">{status.auth_problem} <a href="#/settings/connections">Reconnect YouTube</a></div>}
      {status.quota_paused_until && <div className="banner warn">YouTube API quota is used up for today. Uploads resume at {fmtTime(status.quota_paused_until)}.</div>}
      {!status.secret_storage_is_os && <div className="banner warn small">No OS keychain found, so your keys are stored in a file only your user account can read. <a href="#/guides/troubleshooting">Details</a></div>}

      <Checklist status={status} cats={cats} />

      <section className={`card glow engine-card ${running ? 'on' : ''} ${state === 'paused' ? 'paused' : ''}`}>
        <div className="engine-bg" aria-hidden="true"><i /><i /></div>
        <button className="engine-btn" key={pressed} onClick={() => { setPressed((p) => p + 1); toggleEngine() }} disabled={engineBusy}
          aria-pressed={running} aria-label={running ? 'Stop the engine' : 'Start the engine'}>
          <span className="engine-orbit" aria-hidden="true" />
          <Sticker name="power" />
          <span className="engine-hint">{engineBusy ? 'one sec…' : running ? 'press to stop' : 'press to start'}</span>
        </button>
        <div className="engine-info">
          <div className="caption-state" key={state}>
            <span>{word}</span> <span className="hl">{hl}</span>
          </div>
          <div className="activity">
            {activity.map(([k, a]) => (
              <div key={k + a}><span className="chip accent">{k === 'net' ? 'network' : 'render'}</span> <span>{a}</span></div>
            ))}
            {running && !activity.length && <div className="faint">Waiting for the next job…</div>}
            {!running && <div className="faint">Press the switch and clipped starts finding clips in your categories.</div>}
          </div>
          <div className="next">
            <span className="label">Next upload</span>
            {nu ? (
              <>
                <Clock seconds={left} />
                <span className="next-meta">{fmtTime(nu.at)} · {nu.reason} · “{nu.title?.slice(0, 70)}”</span>
              </>
            ) : (
              <span className="next-meta">{status.auth_problem ? 'On hold until YouTube is reconnected'
                : status.youtube_connected ? 'Nothing approved or ready yet' : 'Connect YouTube to upload'}</span>
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

      <Kicker idx={1} name="Numbers" meta={`${status.uploads_today}/${status.max_uploads_per_day} uploaded today`} />
      <section className="stat-grid">
        <a className="stat glow" href="#/review">
          <span className="stat-top">Waiting for review <span className="arrow">↗</span></span>
          <span className="stat-num"><Count value={items.review || 0} /></span>
        </a>
        <a className="stat glow" href="#/review?tab=scheduled">
          <span className="stat-top">Approved · ready <span className="arrow">↗</span></span>
          <span className="stat-num"><Count value={(items.approved || 0) + (items.ready || 0)} /></span>
        </a>
        <div className="stat glow">
          <span className="stat-top">Rendering</span>
          <span className="stat-num"><Count value={items.processing || 0} /></span>
        </div>
        <a className="stat glow" href="#/history">
          <span className="stat-top">Uploaded total <span className="arrow">↗</span></span>
          <span className="stat-num"><Count value={items.uploaded || 0} /></span>
        </a>
        {items.failed > 0 && (
          <a className="stat glow" href="#/review?tab=failed">
            <span className="stat-top">Failed <span className="arrow">↗</span></span>
            <span className="stat-num warn-text"><Count value={items.failed} /></span>
          </a>
        )}
      </section>

      {status.last_error && <div className="banner warn small">Last error: {status.last_error}</div>}

      <div className="dash-grid">
        <div className="stack">
          <section className="card glow">
            <div className="card-head"><h2>YouTube quota</h2><span className="label">resets {fmtTime(q.resets_at)}</span></div>
            <div className="quota-num"><Count value={q.used || 0} /><small> / {(q.limit || 0).toLocaleString()} units</small></div>
            <div className="meter"><span style={{ width: `${Math.max(quotaPct, 1.5)}%` }} /></div>
            <p className="field-hint">Room for about {q.uploads_left ?? 0} more upload(s) in YouTube's quota today.
              {' '}Your own cap: {status.uploads_today ?? 0}/{status.max_uploads_per_day} today.</p>
            {(status.uploads_today ?? 0) >= status.max_uploads_per_day && (q.uploads_left ?? 0) > 0 &&
              <p className="field-hint warn-text">Scheduled uploads have hit your daily cap. Upload now still works, or raise <a className="link" href="#/settings/mode">Max uploads per day</a>.</p>}
          </section>
          <section className="card glow">
            <div className="card-head"><h2>Watching</h2><a className="ulink" href="#/categories">Edit</a></div>
            {cats === null ? <Loading /> : enabled.length === 0 ? (
              <p className="muted small">No categories yet. <a className="link" href="#/categories">Pick your games</a>.</p>
            ) : (
              <div className="mini-cats">
                {enabled.slice(0, 8).map((c, i) => (
                  <a key={c.id} href="#/categories" className="mini-cat" title={c.name}>
                    <BoxArt src={c.box_art_url} i={i} size="md" />
                    <span className="tip">{c.name}<small>{c.uploads} up</small></span>
                  </a>
                ))}
              </div>
            )}
          </section>
        </div>
        <Logs />
      </div>
    </div>
  )
}
