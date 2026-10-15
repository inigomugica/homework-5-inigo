import { AGENTS, TEAM } from '../agents'
import type { Actor } from '../types'

// Five agents on a pentagon, Boss at the top. Every pair is linked (full connectivity);
// the links in the current handoff chain light up, and the agent speaking now pulses.
const R = 104
const C = 150
const POS = TEAM.map((_, i) => {
  const a = -Math.PI / 2 + (i * 2 * Math.PI) / TEAM.length
  return { x: C + R * Math.cos(a), y: C + R * Math.sin(a) }
})
const at = (a: Actor) => POS[TEAM.indexOf(a)]
const key = (a: string, b: string) => [a, b].sort().join('|')

export function Constellation({ active, chain, seen }: { active: Actor | null; chain: string[]; seen: Set<string> }) {
  const lit = new Set<string>()
  for (let i = 1; i < chain.length; i++) lit.add(key(chain[i - 1], chain[i]))

  return (
    <svg className="constellation" viewBox="0 0 300 300" role="img" aria-label="Agent network">
      <circle cx={C} cy={C} r={R + 30} className="orbit" />
      <circle cx={C} cy={C} r={R - 50} className="orbit faint" />
      {TEAM.flatMap((a, i) =>
        TEAM.slice(i + 1).map((b) => {
          const p = at(a)
          const q = at(b)
          return <line key={a + b} x1={p.x} y1={p.y} x2={q.x} y2={q.y} className={lit.has(key(a, b)) ? 'edge on' : 'edge'} />
        }),
      )}
      {TEAM.map((a) => {
        const p = at(a)
        const m = AGENTS[a]
        return (
          <g
            key={a}
            transform={`translate(${p.x},${p.y})`}
            className={`node ${active === a ? 'active' : ''} ${seen.has(a) ? 'seen' : ''}`}
            style={{ ['--c' as string]: m.color }}
          >
            {active === a && <circle r="30" className="pulse" />}
            <circle r="21" className="core" />
            <text className="glyph" dy="6">
              {m.glyph}
            </text>
            <text className="callsign" dy={p.y < C - 20 ? -32 : 40}>
              {m.callsign}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
