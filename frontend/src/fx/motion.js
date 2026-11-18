// Global motion layer, ported from evzero's site.js and adapted for a React app.
//
//   curtain    .loader in index.html; lifts once fonts are in. The first open
//              of a session plays "clipped" -> CLIPPED rising, then lifts.
//   cursor     dot + lagging ring (+ labels via data-cursor-label) and a soft
//              ambient light trailing it. Fine pointers only.
//   glow       .glow cards light their border near the cursor (--gx/--gy/--ga)
//   magnetic   [data-magnetic="0.2"] elements lean toward the cursor
//   scramble   [data-scramble] text scrambles on hover of its link/button
//   reveals    .reveal / .kicker / [data-split] / .bars get data-in when they
//              scroll into view (an attribute, so React className updates
//              never undo it). New elements are picked up automatically.
//   lenis      smooth wheel scrolling; inner scrollers use data-lenis-prevent
//
// Everything is skipped or simplified under prefers-reduced-motion.

import Lenis from 'lenis'

const doc = document.documentElement
export const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)')
const clamp = (v, a, b) => Math.min(b, Math.max(a, v))

let lenis = null
export const getLenis = () => lenis

const scrollFns = new Set()
export function onScroll(fn) {
  scrollFns.add(fn)
  return () => scrollFns.delete(fn)
}
let scrollQueued = false
function queueScroll() {
  if (scrollQueued) return
  scrollQueued = true
  requestAnimationFrame(() => {
    scrollQueued = false
    const y = window.scrollY
    scrollFns.forEach((fn) => fn(y))
  })
}

function initSmoothScroll() {
  window.addEventListener('scroll', queueScroll, { passive: true })
  window.addEventListener('resize', queueScroll)
  if (reduceMotion) return
  lenis = new Lenis({ duration: 1.1, easing: (t) => 1 - Math.pow(1 - t, 4), smoothWheel: true })
  const raf = (time) => {
    lenis.raf(time)
    requestAnimationFrame(raf)
  }
  requestAnimationFrame(raf)
}

export function scrollToTop(immediate = true) {
  if (lenis) lenis.scrollTo(0, { immediate })
  else window.scrollTo(0, 0)
}

// ------------------------------------------------------------------ curtain
function fontsReady(cap) {
  const ready = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()
  return Promise.race([ready, new Promise((r) => setTimeout(r, cap))])
}

function markReady() {
  doc.classList.add('is-ready')
}

function initCurtain() {
  clearTimeout(window.clippedFailsafe)
  const loader = document.querySelector('.loader')
  if (!loader) return markReady()
  let fresh = false
  if (!reduceMotion) {
    try {
      fresh = !sessionStorage.getItem('clipped-welcomed')
      sessionStorage.setItem('clipped-welcomed', '1')
    } catch {
      /* storage blocked */
    }
  }
  if (!fresh) {
    fontsReady(700).then(() => setTimeout(markReady, 120))
    setTimeout(markReady, 1600)
    return
  }
  fontsReady(1500).then(() => {
    setTimeout(() => {
      loader.classList.add('is-welcome')
      setTimeout(() => {
        loader.classList.add('is-out')
        setTimeout(markReady, 250)
      }, 1700)
    }, 450)
  })
  setTimeout(markReady, 6000) // never strand anyone behind the curtain
}

// ------------------------------------------------------------------ cursor
function initCursor() {
  const dot = document.createElement('div')
  dot.className = 'cursor-dot'
  const ring = document.createElement('div')
  ring.className = 'cursor-ring'
  const label = document.createElement('span')
  label.className = 'cursor-label'
  ring.appendChild(label)
  const ambient = document.createElement('div')
  ambient.className = 'ambient'
  ambient.setAttribute('aria-hidden', 'true')
  document.body.append(ambient, dot, ring)

  const evaluate = () => doc.classList.toggle('has-cursor', finePointer.matches && window.innerWidth > 860 && !reduceMotion)
  evaluate()
  window.addEventListener('resize', evaluate)

  let mx = -100, my = -100, rx = -100, ry = -100, ax = -100, ay = -100
  let seen = false
  let raf = 0
  const tick = () => {
    rx += (mx - rx) * 0.18
    ry += (my - ry) * 0.18
    ax += (mx - ax) * 0.06
    ay += (my - ay) * 0.06
    ring.style.transform = `translate3d(${rx.toFixed(2)}px,${ry.toFixed(2)}px,0)`
    ambient.style.transform = `translate3d(${ax.toFixed(1)}px,${ay.toFixed(1)}px,0)`
    raf = Math.abs(mx - ax) > 0.5 || Math.abs(my - ay) > 0.5 ? requestAnimationFrame(tick) : 0
  }
  window.addEventListener('mousemove', (e) => {
    mx = e.clientX
    my = e.clientY
    if (!seen) {
      seen = true
      rx = ax = mx
      ry = ay = my
      doc.classList.add('cursor-seen')
    }
    doc.classList.remove('cursor-out')
    dot.style.transform = `translate3d(${mx}px,${my}px,0)`
    if (!raf) raf = requestAnimationFrame(tick)
  }, { passive: true })
  document.addEventListener('mouseleave', () => doc.classList.add('cursor-out'))

  const hoverables = 'a, button, [data-cursor], input, textarea, select, label, summary, [role="button"]'
  // Labels can change while hovered (e.g. Go -> Stop): watch the attribute.
  let watched = null
  const labelWatch = new MutationObserver(() => {
    if (watched) label.textContent = watched.getAttribute('data-cursor-label') || ''
  })
  document.addEventListener('mouseover', (e) => {
    const t = e.target
    if (!t || !t.closest) return
    const labelled = t.closest('[data-cursor-label]')
    if (labelled !== watched) {
      labelWatch.disconnect()
      watched = labelled
      if (labelled) labelWatch.observe(labelled, { attributes: true, attributeFilter: ['data-cursor-label'] })
    }
    if (labelled) {
      label.textContent = labelled.getAttribute('data-cursor-label')
      ring.classList.add('has-label')
      ring.classList.remove('hover')
      return
    }
    ring.classList.remove('has-label')
    ring.classList.toggle('hover', !!t.closest(hoverables))
  })
}

// ------------------------------------------------------------------ glow cards
function initGlow() {
  if (!finePointer.matches) return
  let px = -9999, py = -9999, queued = false
  const update = () => {
    queued = false
    const vh = window.innerHeight
    document.querySelectorAll('.glow').forEach((c) => {
      const r = c.getBoundingClientRect()
      if (r.bottom < -120 || r.top > vh + 120) return
      const dx = Math.max(r.left - px, 0, px - r.right)
      const dy = Math.max(r.top - py, 0, py - r.bottom)
      const a = clamp(1 - Math.hypot(dx, dy) / 170, 0, 1)
      c.style.setProperty('--gx', `${(px - r.left).toFixed(1)}px`)
      c.style.setProperty('--gy', `${(py - r.top).toFixed(1)}px`)
      c.style.setProperty('--ga', a.toFixed(3))
    })
  }
  const queue = () => {
    if (!queued) {
      queued = true
      requestAnimationFrame(update)
    }
  }
  window.addEventListener('pointermove', (e) => { px = e.clientX; py = e.clientY; queue() }, { passive: true })
  onScroll(queue)
}

// ------------------------------------------------------------------ magnetic
function initMagnetic() {
  if (reduceMotion) return
  let current = null
  document.addEventListener('pointermove', (e) => {
    if (!finePointer.matches) return
    const el = e.target.closest ? e.target.closest('[data-magnetic]') : null
    if (current && current !== el) {
      current.style.translate = ''
      current = null
    }
    if (!el || el.disabled) return
    current = el
    const k = parseFloat(el.getAttribute('data-magnetic')) || 0.25
    const r = el.getBoundingClientRect()
    const x = (e.clientX - r.left - r.width / 2) * k
    const y = (e.clientY - r.top - r.height / 2) * k
    el.style.translate = `${x.toFixed(1)}px ${y.toFixed(1)}px`
  }, { passive: true })
  document.addEventListener('pointerleave', () => { if (current) current.style.translate = '' })
}

// ------------------------------------------------------------------ scramble
const GLYPHS = '!<>-_\\/[]{}=+*^?#01'
export function scramble(el) {
  const final = el.getAttribute('data-text') || el.textContent
  el.setAttribute('data-text', final)
  let frame = 0
  const total = 12
  clearInterval(el._sc)
  el._sc = setInterval(() => {
    frame++
    const solved = (frame / total) * final.length
    el.textContent = final.split('').map((ch, i) => (ch === ' ' || i < solved ? ch : GLYPHS[(Math.random() * GLYPHS.length) | 0])).join('')
    if (frame >= total) {
      clearInterval(el._sc)
      el.textContent = final
    }
  }, 32)
}

function initScramble() {
  if (reduceMotion) return
  let last = null
  document.addEventListener('mouseover', (e) => {
    const host = e.target.closest ? e.target.closest('a, button') : null
    if (!host || host === last) return
    last = host
    const target = host.querySelector('[data-scramble]')
    if (target) scramble(target)
  })
  document.addEventListener('mouseout', (e) => {
    if (last && !last.contains(e.relatedTarget)) last = null
  })
}

// ------------------------------------------------------------------ reveals
const REVEAL_SEL = '.reveal, .kicker, [data-split], .bars, .hours, .meter'
function initReveals() {
  if (!('IntersectionObserver' in window)) return
  doc.classList.add('reveal-on')
  const io = new IntersectionObserver((entries) => {
    entries.forEach((en) => {
      if (!en.isIntersecting) return
      en.target.setAttribute('data-in', '')
      io.unobserve(en.target)
    })
  }, { rootMargin: '0px 0px -6% 0px', threshold: 0 })

  const scan = (root) => {
    if (root.nodeType !== 1) return
    if (root.matches(REVEAL_SEL) && !root.hasAttribute('data-in')) io.observe(root)
    root.querySelectorAll(REVEAL_SEL).forEach((el) => { if (!el.hasAttribute('data-in')) io.observe(el) })
  }
  scan(document.body)
  new MutationObserver((muts) => {
    muts.forEach((m) => m.addedNodes.forEach(scan))
  }).observe(document.body, { childList: true, subtree: true })
}

// ------------------------------------------------------------------ boot
let booted = false
export function bootMotion() {
  if (booted) return
  booted = true
  initSmoothScroll()
  initCurtain()
  initCursor()
  initGlow()
  initMagnetic()
  initScramble()
  initReveals()
  queueScroll()
}
