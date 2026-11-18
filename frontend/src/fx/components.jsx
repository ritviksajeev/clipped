// Motion building blocks for the clipped dashboard (evzero design language).
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { getLenis, reduceMotion } from './motion.js'

// Deterministic PRNG so split letters don't re-randomize on every render.
function rng(seed) {
  let h = 2166136261
  for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i), 16777619)
  return () => {
    h += 0x6d2b79f5
    let t = h
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function splitWords(text, rand, start) {
  let i = start
  const words = text.split(/(\s+)/).filter(Boolean).map((part, wi) => {
    if (/^\s+$/.test(part)) return ' '
    return (
      <span className="w" key={wi}>
        {[...part].map((ch, ci) => {
          const style = {
            '--y': `${((rand() * 2 - 1) * 0.35).toFixed(3)}em`,
            '--s': (0.55 + rand() * 1.1).toFixed(3),
            '--b': `${(6 + rand() * 10).toFixed(1)}px`,
            '--cd': `${(rand() * 0.45 + i++ * 0.012).toFixed(3)}s`,
          }
          return <span className="ch" key={ci} style={style}>{ch}</span>
        })}
      </span>
    )
  })
  return [words, i]
}

/** Per-letter blur-in title: <Title text="clip" accent="control." /> */
export function Title({ text, accent, as: Tag = 'h1', className = 'ph-title' }) {
  const content = useMemo(() => {
    const rand = rng(`${text}|${accent || ''}`)
    const [a, n] = splitWords(text, rand, 0)
    const [b] = accent ? splitWords(accent, rand, n) : [null]
    return (
      <>
        {a}
        {accent && <> <span className="accent">{b}</span></>}
      </>
    )
  }, [text, accent])
  return (
    <Tag className={className} data-split="">
      <span className="sr-only">{text}{accent ? ` ${accent}` : ''}</span>
      <span className="split-vis" aria-hidden="true">{content}</span>
    </Tag>
  )
}

/** Sub-page hero: meta row, big title, lead. */
export function PageHead({ crumb, meta, text, accent, lead, children }) {
  return (
    <header className="ph">
      <div className="ph-top">
        <span><span className="dot" />clipped / {crumb}</span>
        {meta && <span>{meta}</span>}
      </div>
      <div className="ph-main">
        <Title text={text} accent={accent} />
        {(lead || children) && (
          <div className="ph-side reveal d2">
            {lead && <p className="ph-lead">{lead}</p>}
            {children}
          </div>
        )}
      </div>
    </header>
  )
}

/** "● (01) NAME ———————— meta" section kicker. */
export function Kicker({ idx, name, meta }) {
  return (
    <div className="kicker">
      <span className="k-idx"><span className="dot" />({String(idx).padStart(2, '0')})</span>
      <span className="k-name">{name}</span>
      <span className="k-line" />
      <span className="k-meta">{meta}</span>
    </div>
  )
}

/** Number that counts up (and tweens between live updates). */
export function Count({ value, decimals = 0, format }) {
  const [shown, setShown] = useState(reduceMotion ? value : 0)
  const from = useRef(0)
  const ref = useRef(null)
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    if (!ref.current || !('IntersectionObserver' in window)) { setVisible(true); return }
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setVisible(true); io.disconnect() } })
    io.observe(ref.current)
    return () => io.disconnect()
  }, [])
  useEffect(() => {
    if (!visible) return
    const target = Number(value) || 0
    if (reduceMotion) { setShown(target); return }
    const start = from.current
    const t0 = performance.now()
    const dur = start === 0 ? 1400 : 600
    let raf
    const frame = (now) => {
      const p = Math.min((now - t0) / dur, 1)
      const eased = 1 - Math.pow(1 - p, 4)
      setShown(start + (target - start) * eased)
      if (p < 1) raf = requestAnimationFrame(frame)
      else from.current = target
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [value, visible])
  const n = Number(shown.toFixed(decimals))
  return <span ref={ref} className="count">{format ? format(n) : n.toLocaleString(undefined, { maximumFractionDigits: decimals })}</span>
}

/** Words that swap with a flip: <Flip words={['shorts','hype']} /> */
export function Flip({ words, every = 2600 }) {
  const [i, setI] = useState(0)
  const [phase, setPhase] = useState('in')
  useEffect(() => {
    if (reduceMotion || words.length < 2) return
    const t = setInterval(() => {
      if (document.hidden) return
      setPhase('out')
      setTimeout(() => { setI((x) => (x + 1) % words.length); setPhase('in') }, 430)
    }, every)
    return () => clearInterval(t)
  }, [words, every])
  return <span className={`flip ${phase}`}><span>{words[i]}</span></span>
}

/** Infinite marquee: children rendered as a repeated group. */
export function Marquee({ items, speed = 50, reverse = false }) {
  const group = (
    <span className="mq-group">
      {items.map((t, i) => <React.Fragment key={i}><span>{t}</span><i className="mq-dia" /></React.Fragment>)}
    </span>
  )
  const dur = Math.max(18, items.join('').length * 60 / speed)
  return (
    <div className={`marquee ${reverse ? 'reverse' : ''}`} aria-hidden="true">
      <div className="marquee-track" style={{ '--dur': `${dur}s` }}>
        {group}{group}{group}{group}
      </div>
    </div>
  )
}

/** Warp field: stars streaming toward you, with three drifting aurora lights.
 *  `speed` is the cruising speed; bump `burst` to fire a hard burn. */
export function Warp({ speed = 0.0011, burst = 0 }) {
  const host = useRef(null)
  const state = useRef({ speed, boost: 0 })
  state.current.speed = speed
  useEffect(() => { if (burst) state.current.boost = 0.05 }, [burst])

  useEffect(() => {
    const el = host.current
    const canvas = el.querySelector('canvas')
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const COUNT = window.innerWidth < 700 ? 140 : 260
    const stars = []
    const spawn = (s, anywhere) => {
      s.x = Math.random() * 2 - 1
      s.y = Math.random() * 2 - 1
      s.z = anywhere ? Math.random() * 0.95 + 0.05 : 1
      s.tint = Math.random()
    }
    for (let i = 0; i < COUNT; i++) { const s = {}; spawn(s, true); stars.push(s) }
    let w = 0, h = 0, dpr = 1
    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 1.6)
      w = el.clientWidth
      h = el.clientHeight
      canvas.width = Math.max(1, Math.round(w * dpr))
      canvas.height = Math.max(1, Math.round(h * dpr))
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(el)
    let px = 0, py = 0, tx = 0, ty = 0
    const onMove = (e) => { tx = e.clientX / window.innerWidth - 0.5; ty = e.clientY / window.innerHeight - 0.5 }
    window.addEventListener('mousemove', onMove, { passive: true })
    const draw = (v) => {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      const cx = w / 2 - px * 60
      const cy = h * 0.48 - py * 40
      const k = Math.max(w, h) * 0.62
      ctx.lineCap = 'round'
      for (const s of stars) {
        const z0 = s.z
        s.z -= v
        if (s.z <= 0.02) { spawn(s, false); continue }
        const x1 = cx + (s.x / s.z) * k, y1 = cy + (s.y / s.z) * k
        if (x1 < -40 || x1 > w + 40 || y1 < -40 || y1 > h + 40) { spawn(s, false); continue }
        const zt = Math.min(1, z0 + v * 3)
        const x0 = cx + (s.x / zt) * k, y0 = cy + (s.y / zt) * k
        const near = 1 - s.z
        ctx.strokeStyle = s.tint > 0.62 ? `rgba(180,165,255,${(near * 0.9).toFixed(3)})` : `rgba(243,240,234,${(near * 0.7).toFixed(3)})`
        ctx.lineWidth = 0.4 + near * 1.5
        ctx.beginPath()
        ctx.moveTo(x0, y0)
        ctx.lineTo(x1, y1)
        ctx.stroke()
      }
    }
    if (reduceMotion) { draw(0); return () => { ro.disconnect(); window.removeEventListener('mousemove', onMove) } }
    let visible = true, running = false, alive = true
    const tick = () => {
      if (!alive || !visible || document.hidden) { running = false; return }
      px += (tx - px) * 0.04
      py += (ty - py) * 0.04
      const lenis = getLenis()
      const vel = lenis ? Math.abs(lenis.velocity || 0) : 0
      const st = state.current
      st.boost = Math.max(st.boost * 0.955, Math.min(0.03, vel * 0.0006))
      draw(st.speed + st.boost)
      requestAnimationFrame(tick)
    }
    const start = () => { if (!running) { running = true; requestAnimationFrame(tick) } }
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible) start() })
    io.observe(el)
    const onVis = () => { if (!document.hidden) start() }
    document.addEventListener('visibilitychange', onVis)
    state.current.boost = 0.04
    start()
    return () => {
      alive = false
      io.disconnect()
      ro.disconnect()
      window.removeEventListener('mousemove', onMove)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [])

  return (
    <div className="warp" ref={host} aria-hidden="true">
      <div className="aurora"><i /><i /><i /></div>
      <canvas />
    </div>
  )
}

/** The clipped sticker: a short with a caption bar, die-cut like evzero's stickers. */
export function Sticker({ className = 'stk' }) {
  const INK = '#0d0b14', P1 = '#8a78f0', P2 = '#b4a5ff', LAV = '#dcd6ff', DEEP = '#4c3aa8', WHITE = '#f6f3ee'
  return (
    <svg className={className} viewBox="0 0 200 200" aria-hidden="true" focusable="false">
      <g fill={WHITE} stroke={WHITE} strokeWidth="22" strokeLinejoin="round" strokeLinecap="round">
        <rect x="50" y="18" width="100" height="164" rx="24" />
      </g>
      <g stroke={INK} strokeWidth="7" strokeLinejoin="round" strokeLinecap="round">
        <rect x="50" y="18" width="100" height="164" rx="24" fill={P1} />
        <rect x="64" y="36" width="72" height="96" rx="12" fill={INK} stroke={LAV} strokeWidth="5" />
        <path d="M90 66L114 84L90 102Z" fill={WHITE} stroke="none" />
        <rect x="62" y="144" width="76" height="20" rx="10" fill={LAV} />
        <rect x="70" y="150" width="22" height="8" rx="4" fill={DEEP} stroke="none" />
        <rect x="98" y="150" width="32" height="8" rx="4" fill={P2} stroke="none" />
      </g>
    </svg>
  )
}
