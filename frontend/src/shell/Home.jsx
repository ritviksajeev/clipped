import React, { useEffect, useRef } from 'react'
import { fmtDuration } from '../api.js'
import { useNow } from '../fx.js'
import { Sticker } from '../stickers.jsx'

// Home is the sticker menu: the four places you go most, big; the rest, small;
// and the engine switch as a sticker of its own. One quiet line says what's going on.
export const MAIN = ['dashboard', 'review', 'categories', 'settings']
export const MORE = ['history', 'insights', 'guides']

function Line({ status }) {
  const now = useNow()
  if (!status) return <p className="home-line">&nbsp;</p>
  if (status.offline) return <p className="home-line bad-text">Can't reach the clipped engine.</p>
  const waiting = status.items?.review || 0
  const nu = status.next_upload
  const left = nu ? Math.max(0, (new Date(nu.at).getTime() - now) / 1000) : null
  const bits = [
    status.running ? (status.state === 'paused' ? 'Paused' : 'Running') : 'Stopped',
    waiting ? `${waiting} waiting for you` : 'nothing to review',
    nu ? (left > 0 ? `next upload in ${fmtDuration(left)}` : 'uploading next') : null,
  ].filter(Boolean)
  return (
    <p className="home-line">
      <span className={`led ${status.running ? (status.state === 'paused' ? 'paused' : 'on') : ''}`} />
      {bits.join(' · ')}
    </p>
  )
}

export default function Home({ nav, status, onEngine, engineBusy }) {
  const first = useRef(null)
  useEffect(() => { const t = setTimeout(() => first.current?.focus({ preventScroll: true }), 600); return () => clearTimeout(t) }, [])
  const byKey = Object.fromEntries(nav.map((n) => [n.key, n]))
  const waiting = status?.items?.review || 0
  const item = (key, i, small) => {
    const n = byKey[key]
    return (
      <a key={key} ref={i === 0 ? first : undefined} href={`#/${key}`} className={`home-item ${small ? 'small' : ''}`}
        style={{ '--i': i, '--r': `${n.r}deg` }} aria-label={n.label}>
        <Sticker name={key} />
        {key === 'review' && waiting > 0 && <span className="home-badge" key={waiting}>{waiting}</span>}
        <span className="home-label">{n.label}<small>{key === 'review' && waiting ? `${waiting} waiting` : n.note}</small></span>
      </a>
    )
  }
  return (
    <div className="home">
      <Line status={status} />
      <nav className="home-main" aria-label="clipped">{MAIN.map((k, i) => item(k, i))}</nav>
      <div className="home-more">
        {MORE.map((k, i) => item(k, i + 4, true))}
        <button type="button" className={`home-item small engine ${status?.running ? 'on' : ''}`} style={{ '--i': 7, '--r': '5deg' }}
          onClick={onEngine} disabled={engineBusy || !status || status.offline} aria-label={status?.running ? 'Stop the engine' : 'Start the engine'}>
          <Sticker name="power" />
          <span className="home-label">{status?.running ? 'Stop' : 'Start'}<small>{status?.running ? 'engine on' : 'engine off'}</small></span>
        </button>
      </div>
      <p className="home-keys"><kbd>Ctrl</kbd> <kbd>1</kbd>–<kbd>7</kbd> jump anywhere · <kbd>Esc</kbd> back here</p>
    </div>
  )
}
