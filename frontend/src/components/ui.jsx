import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export function Field({ label, hint, children, wide }) {
  return (
    <label className={`field ${wide ? 'wide' : ''}`}>
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}

export function Toggle({ checked, onChange, label, hint, disabled }) {
  return (
    <label className={`toggle ${disabled ? 'disabled' : ''}`}>
      <input type="checkbox" checked={!!checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="track"><span className="thumb" /></span>
      <span>
        <span className="toggle-label">{label}</span>
        {hint && <span className="field-hint block">{hint}</span>}
      </span>
    </label>
  )
}

export function NumberInput({ value, onChange, min, max, step = 1 }) {
  return (
    <input type="number" value={value ?? ''} min={min} max={max} step={step}
      onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />
  )
}

export function Select({ value, onChange, options }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => {
        const [v, l] = Array.isArray(o) ? o : [o, o]
        return <option key={v} value={v}>{l}</option>
      })}
    </select>
  )
}

export function TagInput({ value = [], onChange, placeholder, prefix = '' }) {
  const [text, setText] = useState('')
  const add = (raw) => {
    const parts = raw.split(/[\s,]+/).map((p) => p.trim()).filter(Boolean)
    if (!parts.length) return
    const next = [...value]
    for (let p of parts) {
      if (prefix && !p.startsWith(prefix)) p = prefix + p.replace(/^[#@]/, '')
      if (!next.some((x) => x.toLowerCase() === p.toLowerCase())) next.push(p)
    }
    onChange(next)
    setText('')
  }
  return (
    <div className="tag-input">
      {value.map((t) => (
        <span className="tag" key={t}>
          {t}
          <button type="button" aria-label={`Remove ${t}`} onClick={() => onChange(value.filter((x) => x !== t))}>×</button>
        </span>
      ))}
      <input value={text} placeholder={placeholder} onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add(text) }
          if (e.key === 'Backspace' && !text && value.length) onChange(value.slice(0, -1))
        }}
        onBlur={() => add(text)} />
    </div>
  )
}

export function Modal({ title, children, onClose, actions }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose?.()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <h2>{title}</h2>
        <div className="modal-body">{children}</div>
        <div className="modal-actions">{actions}</div>
      </div>
    </div>
  )
}

export function AutoWarning({ onAccept, onCancel }) {
  const [checked, setChecked] = useState(false)
  const [busy, setBusy] = useState(false)
  return (
    <Modal title="Before you turn on Auto mode" onClose={onCancel} actions={<>
      <button className="btn ghost" onClick={onCancel}>Cancel</button>
      <button className="btn primary" disabled={!checked || busy} onClick={async () => {
        setBusy(true)
        try { await api.post('/api/settings/acknowledge-auto'); await onAccept() } finally { setBusy(false) }
      }}>I understand, enable Auto mode</button>
    </>}>
      <p>In Auto mode ClipPilot selects, renders and uploads clips to your channel <strong>without asking you first</strong>.</p>
      <ul>
        <li>You are responsible for having permission from each streamer to repost their clips.</li>
        <li>You are responsible for following the Twitch Terms of Service and YouTube's Community Guidelines and policies, including the reused-content rules.</li>
        <li>"Approved streamers only" is on by default: clips from streamers you haven't approved go to the review queue instead of being uploaded.</li>
        <li>Uploads are rate-limited by your interval, daily cap and minimum gap.</li>
      </ul>
      <label className="check">
        <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
        I understand and accept responsibility for what ClipPilot uploads.
      </label>
      <p className="muted small">You'll only see this once. Read more in <a href="#/guides/safety">Auto mode & staying safe</a>.</p>
    </Modal>
  )
}

export function Bars({ rows, labelKey = 'key', valueKey = 'avg_views', format = (v) => v, empty = 'No data yet' }) {
  if (!rows?.length) return <p className="muted">{empty}</p>
  const max = Math.max(...rows.map((r) => r[valueKey] || 0), 1)
  return (
    <div className="bars">
      {rows.map((r) => (
        <div className="bar-row" key={r[labelKey]}>
          <span className="bar-label" title={r[labelKey]}>{r[labelKey]}</span>
          <span className="bar-track"><span className="bar-fill" style={{ width: `${((r[valueKey] || 0) / max) * 100}%` }} /></span>
          <span className="bar-value">{format(r[valueKey])}{r.n != null && <span className="muted small"> · {r.n}</span>}</span>
        </div>
      ))}
    </div>
  )
}

export function Empty({ title, children }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      <div className="muted">{children}</div>
    </div>
  )
}
