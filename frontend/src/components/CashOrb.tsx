import { useEffect, useRef, useState } from 'react'
import { money } from '../agents'

/** The checking balance. It counts down to the new value and flashes the change after a payment. */
export function CashOrb({ balance, asOf }: { balance: number | null; asOf?: string }) {
  const [shown, setShown] = useState(balance ?? 0)
  const [delta, setDelta] = useState<number | null>(null)
  const prev = useRef<number | null>(null)

  useEffect(() => {
    if (balance === null) return
    const from = prev.current ?? balance
    prev.current = balance
    if (from === balance) {
      setShown(balance)
      return
    }
    setDelta(balance - from)
    const t0 = performance.now()
    let raf = 0
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / 1200)
      setShown(from + (balance - from) * (1 - Math.pow(1 - k, 3)))
      if (k < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    const clear = setTimeout(() => setDelta(null), 4000)
    return () => {
      cancelAnimationFrame(raf)
      clearTimeout(clear)
    }
  }, [balance])

  const low = balance !== null && balance < 500
  return (
    <div className={`cash ${low ? 'low' : ''}`}>
      <div className="cash-label">CHECKING</div>
      <div className="cash-value">{balance === null ? '—' : money(delta === null ? balance : shown)}</div>
      <div className="cash-sub">
        {delta !== null ? (
          <span className={delta < 0 ? 'delta out' : 'delta in'}>
            {delta < 0 ? '▼ ' : '▲ '}
            {money(Math.abs(delta))}
          </span>
        ) : (
          <span>as of {asOf ?? '—'} · cash out only</span>
        )}
      </div>
    </div>
  )
}
