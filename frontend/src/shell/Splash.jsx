import React, { useEffect, useState } from 'react'
import { Sticker } from '../stickers.jsx'
import PhoneLogo from './PhoneLogo.jsx'

const reduce = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

// Every launch: the sticker pops in, "clipped / by evzero" settles under it, the
// sticker comes alive as a phone swiping through Shorts, then the splash lifts
// away. `ready` is false until the licence check has answered; the splash waits
// for it so the next screen is never a guess. Click or any key skips ahead.
export default function Splash({ ready, onDone }) {
  const [stage, setStage] = useState(0) // 0 sticker · 1 word · 2 phone · 3 leaving
  const [minDone, setMinDone] = useState(false)

  useEffect(() => {
    const fast = reduce()
    const at = fast ? [0, 150, 300, 700] : [0, 380, 1250, 3300]
    const timers = [
      setTimeout(() => setStage(1), at[1]),
      setTimeout(() => setStage(2), at[2]),
      setTimeout(() => setMinDone(true), at[3]),
    ]
    const skip = () => setMinDone(true)
    window.addEventListener('keydown', skip)
    window.addEventListener('pointerdown', skip)
    return () => {
      timers.forEach(clearTimeout)
      window.removeEventListener('keydown', skip)
      window.removeEventListener('pointerdown', skip)
    }
  }, [])

  useEffect(() => {
    if (minDone && ready && stage !== 3) setStage(3)
  }, [minDone, ready, stage])
  useEffect(() => {
    if (stage !== 3) return
    const t = setTimeout(onDone, reduce() ? 150 : 650)
    return () => clearTimeout(t)
  }, [stage, onDone])

  return (
    <div className={`splash stage-${stage}`} role="img" aria-label="clipped by evzero">
      <div className="splash-mark">
        <span className="splash-stk"><Sticker name="clipped" /></span>
        <span className="splash-phone"><PhoneLogo size={190} swiping={stage >= 2} /></span>
      </div>
      <div className="splash-word">clipped<i /></div>
      <div className="splash-by">by <b>evzero</b></div>
    </div>
  )
}
