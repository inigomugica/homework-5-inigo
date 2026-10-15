import { useEffect, useRef } from 'react'
import { AGENTS, describe } from '../agents'
import type { AgentEvent } from '../types'

/** The live transmission log: one line per agent step, coloured by agent and indented by handoff depth. */
export function Feed({ events, live }: { events: AgentEvent[]; live: boolean }) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight
  }, [events.length])
  const rows = events.flatMap((e) => {
    const d = describe(e)
    return d ? [{ e, d }] : []
  })

  return (
    <div className="feed" ref={box}>
      {rows.length === 0 && (
        <div className="feed-empty">{live ? 'Opening channel…' : 'No transmissions yet. Engage the team to start a run.'}</div>
      )}
      {rows.map(({ e, d }) => {
        const m = AGENTS[e.agent] ?? AGENTS.system
        return (
          <div
            key={e.line}
            className={`tx ${d.tone ?? ''}`}
            style={{ ['--c' as string]: m.color, ['--depth' as string]: Math.max(0, e.chain.length - 1) }}
          >
            <span className="tx-time">{e.ts.slice(11, 19)}</span>
            <span className="tx-who">
              {m.glyph} {m.callsign}
            </span>
            <span className="tx-verb">{d.verb}</span>
            <span className="tx-text">{d.text}</span>
          </div>
        )
      })}
      {live && (
        <div className="tx typing">
          <span className="dots">
            <i />
            <i />
            <i />
          </span>
        </div>
      )}
    </div>
  )
}
