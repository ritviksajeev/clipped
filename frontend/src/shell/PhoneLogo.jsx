import React from 'react'

// clipped's sticker, alive: the same tilted phone with its die-cut edge, but the
// screen is a feed of Shorts being swiped up, one after another. Drawn in CSS so
// the feed can move; sizes follow the sticker's 200-unit artwork (--u = 1 unit).
const FEED = [
  { words: ['no', 'way', 'he', 'hit', 'that'], hot: 3, tone: 'a' },
  { words: ['wait', 'for', 'it'], hot: 2, tone: 'b' },
  { words: ['clutch'], hot: 0, tone: 'c' },
  { words: ['chat', 'is', 'this', 'real'], hot: 3, tone: 'd' },
]

function Short({ s }) {
  return (
    <div className={`pl-short t-${s.tone}`}>
      <span className="pl-scene" />
      <span className="pl-cap">
        {s.words.map((w, i) => <span key={i} className={i === s.hot ? 'hot' : ''}>{w}</span>)}
      </span>
      <span className="pl-side"><i /><i /><i /></span>
      <span className="pl-meta" />
    </div>
  )
}

export default function PhoneLogo({ size = 140, swiping = true, className = '' }) {
  return (
    <div className={`phone-logo ${swiping ? 'swiping' : ''} ${className}`} style={{ '--u': `${size / 200}px` }} aria-hidden="true">
      <div className="pl-body">
        <div className="pl-screen">
          <div className="pl-feed">
            {FEED.map((s, i) => <Short key={i} s={s} />)}
            <Short s={FEED[0]} />{/* the first again, so the loop is seamless */}
          </div>
        </div>
        <div className="pl-bar"><i /><i /></div>
      </div>
    </div>
  )
}
