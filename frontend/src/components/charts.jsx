import React, { useState } from 'react'
import { fmtNum } from '../api.js'

// Small hand-drawn SVG charts: no chart library, animated with CSS, sized by viewBox.

const W = 640
const H = 200
const PAD = { l: 8, r: 8, t: 16, b: 26 }

// Last N days: Shorts made (ghost bars), uploaded (solid bars) and their views (a line).
export function ActivityChart({ days }) {
  const [hover, setHover] = useState(null)
  if (!days?.length) return null
  const n = days.length
  const slot = (W - PAD.l - PAD.r) / n
  const bw = Math.min(22, slot * 0.56)
  const maxCount = Math.max(2, ...days.map((d) => Math.max(d.made, d.uploaded)))
  const maxViews = Math.max(1, ...days.map((d) => d.views))
  const plotH = H - PAD.t - PAD.b
  const y = (v, max) => PAD.t + plotH - (v / max) * plotH
  const cx = (i) => PAD.l + slot * i + slot / 2
  const hasViews = days.some((d) => d.views > 0)
  const line = days.map((d, i) => `${i ? 'L' : 'M'}${cx(i).toFixed(1)} ${y(d.views, maxViews).toFixed(1)}`).join(' ')
  const area = `${line} L${cx(n - 1).toFixed(1)} ${PAD.t + plotH} L${cx(0).toFixed(1)} ${PAD.t + plotH} Z`
  const label = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
  const h = hover != null ? days[hover] : null
  return (
    <div className="chart" onPointerLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Shorts made and uploaded over the last ${n} days`}>
        <defs>
          <linearGradient id="viewsFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#b4a5ff" stopOpacity="0.28" />
            <stop offset="1" stopColor="#b4a5ff" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line key={f} className="grid" x1={PAD.l} x2={W - PAD.r} y1={PAD.t + plotH * (1 - f)} y2={PAD.t + plotH * (1 - f)} />
        ))}
        {days.map((d, i) => (
          <g key={d.day} className={`day ${hover === i ? 'on' : ''}`} style={{ '--i': i }}>
            <rect className="made" x={cx(i) - bw / 2} width={bw} y={y(d.made, maxCount)} height={Math.max(0, PAD.t + plotH - y(d.made, maxCount))} rx="4" />
            <rect className="up" x={cx(i) - bw / 2 + 3} width={Math.max(2, bw - 6)} y={y(d.uploaded, maxCount)} height={Math.max(0, PAD.t + plotH - y(d.uploaded, maxCount))} rx="3" />
            {(i % 2 === (n - 1) % 2) && <text className="tick" x={cx(i)} y={H - 8} textAnchor="middle">{label(d.day)}</text>}
            <rect className="hit" x={PAD.l + slot * i} width={slot} y={0} height={H} onPointerEnter={() => setHover(i)} />
          </g>
        ))}
        {hasViews && <>
          <path className="views-area" d={area} />
          <path className="views" d={line} pathLength="1" />
        </>}
        <line className="base" x1={PAD.l} x2={W - PAD.r} y1={PAD.t + plotH} y2={PAD.t + plotH} />
      </svg>
      <div className={`chart-tip ${h ? 'show' : ''}`} style={h ? { left: `${(cx(hover) / W) * 100}%` } : undefined}>
        {h && <><b>{label(h.day)}</b><span>{h.made} made · {h.uploaded} uploaded{hasViews ? ` · ${fmtNum(h.views)} views` : ''}</span></>}
      </div>
      <div className="chart-key">
        <span><i className="k-made" />made</span><span><i className="k-up" />uploaded</span>{hasViews && <span><i className="k-views" />views</span>}
      </div>
    </div>
  )
}

// A ring that fills to `value / max`, with the number in the middle.
export function Ring({ value, max, label, sub, size = 112 }) {
  const r = 46
  const c = 2 * Math.PI * r
  const f = Math.max(0, Math.min(1, max ? value / max : 0))
  return (
    <div className="ring" style={{ width: size, height: size }}>
      <svg viewBox="0 0 110 110" aria-hidden="true">
        <circle className="ring-track" cx="55" cy="55" r={r} />
        <circle className={`ring-fill ${f > 0.85 ? 'hot' : ''}`} cx="55" cy="55" r={r} strokeDasharray={c} style={{ '--off': c * (1 - f) }} />
      </svg>
      <div className="ring-text"><b>{label}</b>{sub && <small>{sub}</small>}</div>
    </div>
  )
}

// A tiny trend line for a stat tile.
export function Spark({ values }) {
  if (!values?.length || values.every((v) => !v)) return null
  const max = Math.max(...values, 1)
  const pts = values.map((v, i) => `${(i / Math.max(1, values.length - 1)) * 100},${28 - (v / max) * 24}`).join(' ')
  return (
    <svg className="spark" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={pts} pathLength="1" />
    </svg>
  )
}
