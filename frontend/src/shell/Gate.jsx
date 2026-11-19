import React, { useEffect, useRef, useState } from 'react'
import { api, openPage } from '../api.js'
import { Sticker } from '../stickers.jsx'
import PhoneLogo from './PhoneLogo.jsx'

const BUY_URL = 'https://evzero.org/clipped/buy/'

// The welcome screen. Two ways in: a free day (a few ads on evzero.org, then the app
// unlocks itself) or Pro ($2.99/month, no watermark). A key can also be pasted.
export default function Gate({ license, onUnlocked }) {
  const [key, setKey] = useState('')
  const [error, setError] = useState(license?.problem || '')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState('')
  const [shake, setShake] = useState(0)
  const [done, setDone] = useState(null)
  const [waiting, setWaiting] = useState(null) // the free day being unlocked in the browser
  const [showKey, setShowKey] = useState(false)
  const field = useRef(null)
  const buyUrl = license?.buy_url || BUY_URL

  useEffect(() => { if (showKey) setTimeout(() => field.current?.focus(), 200) }, [showKey])

  const unlocked = (r) => {
    setDone(r)
    setTimeout(() => onUnlocked(r), 1100)
  }

  // Poll for the free day the browser is unlocking.
  useEffect(() => {
    if (!waiting) return
    const started = Date.now()
    const t = setInterval(async () => {
      try {
        const r = await api.get(`/api/license/free/${waiting}`)
        if (r.done) { clearInterval(t); setWaiting(null); unlocked(r) }
      } catch (e) {
        clearInterval(t); setWaiting(null); setError(e.message)
      }
      if (Date.now() - started > 15 * 60 * 1000) { clearInterval(t); setWaiting(null) }
    }, 2500)
    return () => clearInterval(t)
  }, [waiting])

  const freeDay = async () => {
    setError('')
    setBusy('free')
    try {
      const r = await api.post('/api/license/free')
      setWaiting(r.nonce)
      openPage(r.url)
    } catch (e) { setError(e.message) } finally { setBusy('') }
  }

  const submit = async (e, force = false) => {
    e?.preventDefault()
    if (busy || !key.trim()) return
    setBusy(force ? 'move' : 'key')
    setError('')
    setCode('')
    try {
      unlocked(await api.post('/api/license', { key, force }))
    } catch (err) {
      setError(err.message)
      setCode(err.detail?.code || err.code || '')
      setShake((n) => n + 1)
      setBusy('')
    }
  }

  if (done) {
    return (
      <div className="gate unlocked">
        <div className="gate-card">
          <div className="gate-logo"><span className="gate-done"><Sticker name="done" /></span></div>
          <div className="gate-text">
            <h1 className="gate-title">You're in<span className="accent">.</span></h1>
            <p className="gate-lead">{done.tier === 'free'
              ? `Free day · ${done.license?.hours_left ?? 24} hours. Shorts carry a small watermark.`
              : 'Pro. No watermark, no limits. Enjoy.'}</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="gate">
      <div className="gate-card">
        <div className="gate-logo"><PhoneLogo size={112} /></div>
        <div className="gate-text">
          <h1 className="gate-title">Welcome to <span className="serif accent">clipped</span></h1>
          <p className="gate-lead">{error && /free day is over/i.test(error) ? 'Your free day is over. Grab another, or go Pro.' : 'Pick how you want in.'}</p>
        </div>

        {waiting ? (
          <div className="gate-wait">
            <span className="gate-spinner" aria-hidden="true" />
            <p><b>Watch the ads in your browser.</b><br />clipped unlocks by itself when you're done.</p>
            <div className="gate-actions">
              <button className="btn ghost" onClick={freeDay}>Open the page again</button>
              <button className="btn ghost" onClick={() => setWaiting(null)}>Cancel</button>
            </div>
          </div>
        ) : (
          <div className="gate-plans">
            <button className="gate-plan" onClick={freeDay} disabled={!!busy}>
              <span className="tag">Free</span>
              <b>Get a free day</b>
              <span>Watch a few ads · 24 hours · small watermark</span>
              <span className="arrow">{busy === 'free' ? '…' : '→'}</span>
            </button>
            <a className="gate-plan pro" href={buyUrl} target="_blank" rel="noreferrer" onClick={(e) => { e.preventDefault(); openPage(buyUrl) }}>
              <span className="tag good">Pro</span>
              <b>$2.99 a month</b>
              <span>No watermark, no ads, cancel any time</span>
              <span className="arrow">↗</span>
            </a>
          </div>
        )}

        {!waiting && (showKey ? (
          <form className={`gate-form ${error ? 'has-error' : ''}`} onSubmit={submit} key={shake} data-shake={shake ? '1' : undefined}>
            <textarea ref={field} className="gate-key" rows={3} spellCheck={false} autoComplete="off" autoCapitalize="characters"
              placeholder="CLIP-XXXXX-XXXXX-XXXXX-…" value={key} aria-label="Licence key"
              onChange={(e) => { setKey(e.target.value); if (error) { setError(''); setCode('') } }}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) submit(e) }} />
            {error && <p className="gate-error" role="alert">{error}</p>}
            <div className="gate-actions">
              {code === 'device_limit'
                ? <button type="button" className="btn primary" disabled={!!busy} onClick={(e) => submit(e, true)}>{busy === 'move' ? 'Moving…' : 'Move Pro to this computer'}</button>
                : <button className="btn primary" disabled={!!busy || !key.trim()}>{busy === 'key' ? 'Checking…' : 'Unlock'} <span className="arrow">→</span></button>}
            </div>
          </form>
        ) : (
          <>
            {error && <p className="gate-error" role="alert">{error}</p>}
            <button className="linklike gate-have" onClick={() => setShowKey(true)}>I have a key</button>
          </>
        ))}
        <p className="gate-note">Keys are checked against this computer · your Twitch and YouTube keys never leave it</p>
      </div>
    </div>
  )
}
