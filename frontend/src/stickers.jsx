import React from 'react'

// Die-cut stickers in the evzero.org style: `cut` is the silhouette, drawn fat
// and white underneath; `art` sits on top with ink outlines. One per place in
// the app, plus clipped's own mark.
const INK = '#0d0b14'
const P1 = '#8a78f0'
const P2 = '#b4a5ff'
const LAV = '#dcd6ff'
const DEEP = '#4c3aa8'
const WHITE = '#f6f3ee'

export const STICKERS = {
  clipped: { // the app: a Short with a play button
    cut: '<rect x="50" y="18" width="100" height="164" rx="24" transform="rotate(-8 100 100)"/>',
    art: `<g transform="rotate(-8 100 100)">
            <rect x="50" y="18" width="100" height="164" rx="24" fill="${P1}"/>
            <rect x="64" y="36" width="72" height="96" rx="12" fill="${INK}" stroke="${LAV}" stroke-width="5"/>
            <path d="M90 66L114 84L90 102Z" fill="${WHITE}" stroke="none"/>
            <rect x="62" y="144" width="76" height="20" rx="10" fill="${LAV}"/>
            <rect x="70" y="150" width="22" height="8" rx="4" fill="${DEEP}" stroke="none"/>
            <rect x="98" y="150" width="32" height="8" rx="4" fill="${P2}" stroke="none"/>
          </g>`,
  },
  dashboard: { // a control knob
    cut: '<circle cx="100" cy="100" r="76"/>',
    art: `<circle cx="100" cy="100" r="76" fill="${P1}"/>
          <circle cx="100" cy="100" r="50" fill="${INK}" stroke="${LAV}" stroke-width="6"/>
          <path d="M100 30V44M100 156V170M30 100H44M156 100H170" fill="none" stroke="${INK}" stroke-width="7"/>
          <path d="M90 78L124 100L90 122Z" fill="${WHITE}" stroke="none"/>`,
  },
  power: { // the engine switch
    cut: '<circle cx="100" cy="100" r="78"/>',
    art: `<circle cx="100" cy="100" r="78" fill="${LAV}"/>
          <circle cx="100" cy="100" r="54" fill="${P1}"/>
          <path d="M76 76A34 34 0 1 0 124 76" fill="none" stroke="${INK}" stroke-width="11"/>
          <path d="M100 58V100" fill="none" stroke="${INK}" stroke-width="11"/>`,
  },
  review: { // a Short, checked off
    cut: '<rect x="44" y="20" width="88" height="150" rx="20"/><circle cx="142" cy="138" r="34"/>',
    art: `<rect x="44" y="20" width="88" height="150" rx="20" fill="${LAV}"/>
          <rect x="57" y="37" width="62" height="98" rx="9" fill="${INK}" stroke="none"/>
          <rect x="66" y="94" width="44" height="10" rx="5" fill="${WHITE}" stroke="none"/>
          <rect x="74" y="110" width="28" height="10" rx="5" fill="${P2}" stroke="none"/>
          <circle cx="142" cy="138" r="30" fill="${P1}"/>
          <path d="M128 138L139 149L158 128" fill="none" stroke="${WHITE}" stroke-width="9"/>`,
  },
  history: { // a film reel
    cut: '<circle cx="96" cy="96" r="72"/><path d="M150 150Q176 168 186 150L190 182H120Z"/>',
    art: `<path d="M140 150Q170 172 184 150V180H120Z" fill="${P2}"/>
          <circle cx="96" cy="96" r="72" fill="${DEEP}"/>
          <circle cx="96" cy="58" r="15" fill="${LAV}"/><circle cx="132" cy="84" r="15" fill="${LAV}"/>
          <circle cx="118" cy="128" r="15" fill="${LAV}"/><circle cx="74" cy="128" r="15" fill="${LAV}"/>
          <circle cx="60" cy="84" r="15" fill="${LAV}"/>
          <circle cx="96" cy="96" r="8" fill="${WHITE}" stroke="none"/>`,
  },
  insights: { // a chart that went up
    cut: '<rect x="24" y="32" width="152" height="136" rx="24"/>',
    art: `<rect x="24" y="32" width="152" height="136" rx="24" fill="${WHITE}"/>
          <rect x="48" y="112" width="24" height="34" rx="6" fill="${P2}"/>
          <rect x="88" y="88" width="24" height="58" rx="6" fill="${P1}"/>
          <rect x="128" y="64" width="24" height="82" rx="6" fill="${DEEP}"/>
          <path d="M48 88L86 62L114 72L150 46" fill="none" stroke="${INK}" stroke-width="6"/>`,
  },
  categories: { // a controller
    cut: '<path d="M60 62H140Q178 62 184 104L190 140Q192 162 172 164Q158 165 148 148L138 132H62L52 148Q42 165 28 164Q8 162 10 140L16 104Q22 62 60 62Z"/>',
    art: `<path d="M60 62H140Q178 62 184 104L190 140Q192 162 172 164Q158 165 148 148L138 132H62L52 148Q42 165 28 164Q8 162 10 140L16 104Q22 62 60 62Z" fill="${LAV}"/>
          <path d="M58 86V118M42 102H74" fill="none" stroke="${INK}" stroke-width="10"/>
          <circle cx="132" cy="92" r="9" fill="${P1}"/><circle cx="152" cy="112" r="9" fill="${DEEP}"/>
          <circle cx="112" cy="112" r="9" fill="${P2}"/>`,
  },
  settings: { // sliders
    cut: '<rect x="28" y="28" width="144" height="144" rx="38"/>',
    art: `<rect x="28" y="28" width="144" height="144" rx="38" fill="${P2}"/>
          <path d="M56 76H144M56 124H144" fill="none" stroke="${INK}" stroke-width="8"/>
          <circle cx="84" cy="76" r="15" fill="${WHITE}"/><circle cx="120" cy="124" r="15" fill="${LAV}"/>`,
  },
  guides: { // an open book
    cut: '<path d="M100 54Q72 36 26 40V160Q72 156 100 174Q128 156 174 160V40Q128 36 100 54Z"/>',
    art: `<path d="M100 54Q72 36 26 40V160Q72 156 100 174Q128 156 174 160V40Q128 36 100 54Z" fill="${WHITE}"/>
          <path d="M100 54V172" fill="none"/>
          <path d="M46 72H80M46 94H80M46 116H72M120 72H154M120 94H154M120 116H146" fill="none" stroke="${DEEP}" stroke-width="7"/>
          <path d="M136 38V70L146 62L156 70V38" fill="${P1}" stroke-width="5"/>`,
  },
  key: { // connections
    cut: '<circle cx="70" cy="100" r="44"/><path d="M106 88H178V112H164V132H140V112H106Z"/>',
    art: `<path d="M106 88H178V112H164V132H140V112H106Z" fill="${P1}"/>
          <circle cx="70" cy="100" r="44" fill="${LAV}"/>
          <circle cx="62" cy="100" r="14" fill="${INK}" stroke="none"/>`,
  },
  sparkle: { // AI
    cut: '<path d="M100 20Q110 90 180 100Q110 110 100 180Q90 110 20 100Q90 90 100 20Z"/>',
    art: `<path d="M100 20Q110 90 180 100Q110 110 100 180Q90 110 20 100Q90 90 100 20Z" fill="${P2}"/>
          <path d="M100 66Q104 96 134 100Q104 104 100 134Q96 104 66 100Q96 96 100 66Z" fill="${WHITE}" stroke="none"/>`,
  },
  empty: { // nothing here yet
    cut: '<circle cx="100" cy="100" r="74"/>',
    art: `<circle cx="100" cy="100" r="74" fill="${INK}" stroke="${P2}" stroke-dasharray="15 13"/>
          <path d="M78 84Q78 60 100 60Q124 60 124 82Q124 96 108 104Q100 108 100 120" fill="none" stroke="${LAV}" stroke-width="11"/>
          <circle cx="100" cy="142" r="8" fill="${LAV}" stroke="none"/>`,
  },
  done: { // all caught up
    cut: '<circle cx="100" cy="100" r="74"/>',
    art: `<circle cx="100" cy="100" r="74" fill="${P1}"/>
          <path d="M66 102L90 126L136 76" fill="none" stroke="${WHITE}" stroke-width="14"/>`,
  },
}

export function Sticker({ name, className = '', style, title }) {
  const s = STICKERS[name] || STICKERS.empty
  return (
    <svg className={`stk ${className}`} viewBox="0 0 200 200" style={style} aria-hidden={title ? undefined : 'true'}
      role={title ? 'img' : undefined} aria-label={title} focusable="false">
      <g fill={WHITE} stroke={WHITE} strokeWidth="22" strokeLinejoin="round" strokeLinecap="round"
        dangerouslySetInnerHTML={{ __html: s.cut }} />
      <g stroke={INK} strokeWidth="7" strokeLinejoin="round" strokeLinecap="round"
        dangerouslySetInnerHTML={{ __html: s.art }} />
    </svg>
  )
}
