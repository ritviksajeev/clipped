import React, { useEffect, useRef, useState } from 'react'
import { api, openExternal } from '../api.js'
import { Sticker } from '../stickers.jsx'
import PhoneLogo from './PhoneLogo.jsx'

const BUY_URL = 'https://evzero.org/clipped/buy/'

// The welcome screen: one field for the licence key and a way to get one.
// Keys are long on purpose (they're signed, so they can't be guessed or made up);
// pasting is the expected way in, and spaces, dashes and case don't matter.
export default function Gate({ license, onUnlocked }) {
  const [key, setKey] = useState('')
  const [error, setError] = useState(license?.problem || '')
  const [busy, setBusy] = useState(false)
  const [shake, setShake] = useState(0)
  const [done, setDone] = useState(null)
  const field = useRef(null)
  const buyUrl = license?.buy_url || BUY_URL
  const expired = /expired/i.test(error)

  useEffect(() => { const t = setTimeout(() => field.current?.focus(), 500); return () => clearTimeout(t) }, [])

  const submit = async (e) => {
    e?.preventDefault()
    if (busy || !key.trim()) return
    setBusy(true)
    setError('')
    try {
      const r = await api.post('/api/license', { key })
      setDone(r.license)
      setTimeout(() => onUnlocked(r), 1100)
    } catch (err) {
      setError(err.message)
      setShake((n) => n + 1)
      setBusy(false)
    }
  }

  return (
    <div className={`gate ${done ? 'unlocked' : ''}`}>
      <div className="gate-card">
        <div className="gate-logo">
          {done ? <span className="gate-done"><Sticker name="done" /></span> : <PhoneLogo size={118} />}
        </div>
        {done ? (
          <div className="gate-text">
            <h1 className="gate-title">You're in<span className="accent">.</span></h1>
            <p className="gate-lead">{done.plan === 'lifetime' ? 'Lifetime licence. Enjoy clipped.' : `Monthly licence · ${done.days_left} days left.`}</p>
          </div>
        ) : (
          <>
            <div className="gate-text">
              <h1 className="gate-title">Welcome to <span className="serif accent">clipped</span></h1>
              <p className="gate-lead">Paste your licence key to start.</p>
            </div>
            <form className={`gate-form ${error ? 'has-error' : ''}`} onSubmit={submit} key={shake} data-shake={shake ? '1' : undefined}>
              <textarea ref={field} className="gate-key" rows={3} spellCheck={false} autoComplete="off" autoCapitalize="characters"
                placeholder="CLIP-XXXXX-XXXXX-XXXXX-…" value={key} aria-label="Licence key"
                onChange={(e) => { setKey(e.target.value); if (error) setError('') }}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) submit(e) }} />
              {error && <p className="gate-error" role="alert">{error}</p>}
              <div className="gate-actions">
                <button className="btn primary" disabled={busy || !key.trim()}>{busy ? 'Checking…' : 'Unlock'} <span className="arrow">→</span></button>
                <a className="btn ghost" href={buyUrl} target="_blank" rel="noreferrer"
                  onClick={(e) => { e.preventDefault(); openExternal(buyUrl) }}>{expired ? 'Renew' : 'Get a key'} <span className="arrow">↗</span></a>
              </div>
            </form>
            <p className="gate-note">$2.99 a month or $32 for life · your key is in the receipt email · checked on this computer, never sent anywhere</p>
          </>
        )}
      </div>
    </div>
  )
}
