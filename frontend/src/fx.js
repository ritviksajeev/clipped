// The motion that suits an app: glow cards lit by the pointer (evzero.org's
// signature), numbers that count up, and mono labels that scramble on hover.
// No smooth-scroll hijacking, custom cursor or page curtain.
import { useEffect, useRef, useState } from 'react'

const reduce = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

export function bootFx() {
  // One listener lights whichever .glow cards are near the pointer.
  let frame = 0
  let last = null
  const paint = () => {
    frame = 0
    if (!last) return
    const { x, y } = last
    document.querySelectorAll('.glow').forEach((el) => {
      const r = el.getBoundingClientRect()
      if (r.bottom < 0 || r.top > window.innerHeight) return
      const gx = x - r.left
      const gy = y - r.top
      const dx = Math.max(r.left - x, 0, x - r.right)
      const dy = Math.max(r.top - y, 0, y - r.bottom)
      const near = Math.max(0, 1 - Math.hypot(dx, dy) / 140)
      el.style.setProperty('--gx', `${gx}px`)
      el.style.setProperty('--gy', `${gy}px`)
      el.style.setProperty('--ga', near.toFixed(3))
    })
  }
  window.addEventListener('pointermove', (e) => {
    last = { x: e.clientX, y: e.clientY }
    if (!frame) frame = requestAnimationFrame(paint)
  }, { passive: true })
  document.addEventListener('pointerleave', () => {
    document.querySelectorAll('.glow').forEach((el) => el.style.setProperty('--ga', '0'))
  })

  // [data-scramble] text shuffles through glyphs on hover, like the site's nav.
  const GLYPHS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/·'
  document.addEventListener('pointerover', (e) => {
    const el = e.target.closest?.('[data-scramble]')
    if (!el || el.dataset.busy || reduce()) return
    const text = el.dataset.text || el.textContent
    el.dataset.text = text
    el.dataset.busy = '1'
    let i = 0
    const tick = () => {
      el.textContent = text.split('').map((c, n) => (n < i || c === ' ' ? c : GLYPHS[Math.floor(Math.random() * GLYPHS.length)])).join('')
      i += 0.6
      if (i <= text.length) requestAnimationFrame(tick)
      else { el.textContent = text; delete el.dataset.busy }
    }
    tick()
  })
}

export function useCountUp(value, ms = 900) {
  const [shown, setShown] = useState(value || 0)
  const from = useRef(value || 0)
  useEffect(() => {
    const target = Number(value) || 0
    if (reduce()) { setShown(target); from.current = target; return }
    const start = performance.now()
    const a = from.current
    let raf
    const step = (t) => {
      const p = Math.min(1, (t - start) / ms)
      const eased = 1 - Math.pow(1 - p, 4)
      setShown(a + (target - a) * eased)
      if (p < 1) raf = requestAnimationFrame(step)
      else from.current = target
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [value, ms])
  return shown
}

export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(t)
  }, [ms])
  return now
}
