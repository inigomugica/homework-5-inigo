import { AGENTS, TEAM } from '../agents'
import type { AgentEvent } from '../types'

interface Report {
  status: string
  summary: string
  tools: Set<string>
}

/** One card per agent: what it concluded on this ticket in the latest run, and the MCP tools it used. */
export function Debrief({ events }: { events: AgentEvent[] }) {
  const reports = new Map<string, Report>()
  for (const e of events) {
    const r = reports.get(e.agent) ?? { status: '', summary: '', tools: new Set<string>() }
    const d = e.detail as { tool?: string; reply?: { status: string; summary: string } }
    if (e.event === 'mcp_call' && d.tool) r.tools.add(d.tool)
    if (e.event === 'run_end' && d.reply) {
      r.status = d.reply.status
      r.summary = d.reply.summary
    }
    reports.set(e.agent, r)
  }
  const shown = TEAM.filter((a) => reports.get(a)?.summary)

  return (
    <div className="debrief">
      {shown.length === 0 && <div className="muted small">Agent reports appear here after a run.</div>}
      {shown.map((a) => {
        const m = AGENTS[a]
        const r = reports.get(a)!
        return (
          <div key={a} className="report" style={{ ['--c' as string]: m.color }}>
            <div className="report-head">
              <span>
                {m.glyph} {m.label}
              </span>
              <span className={`status st-${r.status}`}>{r.status.replace('_', ' ')}</span>
            </div>
            <p>{r.summary}</p>
            {r.tools.size > 0 && (
              <div className="tools">
                {[...r.tools].map((t) => (
                  <code key={t}>{t}</code>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
