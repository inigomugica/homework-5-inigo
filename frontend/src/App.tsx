import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import { AGENTS, STATUS_LABEL } from './agents'
import { ApprovalDock } from './components/ApprovalDock'
import { CashOrb } from './components/CashOrb'
import { Constellation } from './components/Constellation'
import { Debrief } from './components/Debrief'
import { Feed } from './components/Feed'
import { TicketRail } from './components/TicketRail'
import type { Actor, AgentEvent, AgentReply, Approval, Cash, Ticket } from './types'

const POLL_MS = 900

/** Events of the most recent agent run after the last database reset (ignores human clicks). */
function latestRun(events: AgentEvent[], resetLine: number): AgentEvent[] {
  const runs = events.filter((e) => e.agent !== 'human' && e.agent !== 'system' && e.line > resetLine)
  const id = runs.at(-1)?.run_id
  return id ? runs.filter((e) => e.run_id === id) : []
}

export default function App() {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [loose, setLoose] = useState<Approval[]>([])
  const [today, setToday] = useState('')
  const [cash, setCash] = useState<Cash | null>(null)
  // ?ticket=101 opens the deck on that ticket (used for the problem 9 screenshots).
  const [selected, setSelected] = useState<number | null>(() => {
    const t = new URLSearchParams(window.location.search).get('ticket')
    return t ? Number(t) : null
  })
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [running, setRunning] = useState<number | null>(null)
  const [reply, setReply] = useState<AgentReply | null>(null)
  const [deciding, setDeciding] = useState<number | null>(null)
  const [toast, setToast] = useState<{ text: string; tone: 'ok' | 'bad' } | null>(null)
  const [online, setOnline] = useState(true)
  const [resetLine, setResetLine] = useState(0) // audit line of the latest database reset
  const cursor = useRef(0)

  const say = (text: string, tone: 'ok' | 'bad' = 'ok') => {
    setToast({ text, tone })
    setTimeout(() => setToast(null), 5000)
  }

  const refresh = useCallback(async () => {
    try {
      const [t, c] = await Promise.all([api.tickets(), api.cash()])
      setTickets(t.tickets)
      setLoose(t.approvals_without_ticket)
      setToday(t.today)
      setCash(c)
      setOnline(true)
      setSelected((s) => s ?? t.tickets.find((x) => x.state === 'open')?.id ?? t.tickets[0]?.id ?? null)
    } catch {
      setOnline(false)
    }
  }, [])

  const findReset = useCallback(async () => {
    const r = await api.events({ limit: 1000 }).catch(() => null)
    const resets = r?.events.filter((e) => e.event === 'db_reset') ?? []
    setResetLine(resets.at(-1)?.line ?? 0)
  }, [])

  useEffect(() => {
    refresh()
    findReset()
  }, [refresh, findReset])

  // When a ticket is picked, load its history so the feed and debrief show its latest run.
  useEffect(() => {
    if (selected === null || running !== null) return
    setReply(null)
    api
      .events({ ticket_id: selected, limit: 1000 })
      .then((r) => setEvents(latestRun(r.events, resetLine)))
      .catch(() => setEvents([]))
  }, [selected, running, resetLine])

  // One run at a time. Engage, Run the desk and a paid approval all add tickets here.
  const queue = useRef<number[]>([])
  const [queued, setQueued] = useState<number[]>([])
  const working = useRef(false)

  const runOne = async (id: number) => {
    setSelected(id)
    setReply(null)
    setEvents([])
    try {
      cursor.current = (await api.events({ limit: 1 })).next
    } catch {
      say('Backend is offline.', 'bad')
      return
    }
    setRunning(id)
    const poll = setInterval(async () => {
      const r = await api.events({ after: cursor.current, ticket_id: id }).catch(() => null)
      if (!r) return
      cursor.current = r.next
      if (r.events.length) setEvents((prev) => [...prev, ...r.events])
    }, POLL_MS)
    try {
      const out = await api.runTicket(id)
      setReply(out.reply)
    } catch (e) {
      say(`Ticket #${id}: ${(e as Error).message}`, 'bad')
    } finally {
      clearInterval(poll)
      const r = await api.events({ after: cursor.current, ticket_id: id }).catch(() => null)
      if (r?.events.length) setEvents((prev) => [...prev, ...r.events])
      setRunning(null)
      await refresh()
    }
  }

  const enqueue = async (ids: number[]) => {
    for (const id of ids) if (!queue.current.includes(id) && running !== id) queue.current.push(id)
    setQueued([...queue.current])
    if (working.current) return
    working.current = true
    while (queue.current.length) {
      const id = queue.current.shift()!
      setQueued([...queue.current])
      await runOne(id)
    }
    working.current = false
  }

  const engage = (id: number) => enqueue([id])

  // Work every open ticket that isn't just waiting on the human, in board order.
  const runDesk = () =>
    enqueue(
      tickets
        .filter((t) => t.state === 'open' && !t.approvals.some((a) => a.status === 'pending' || a.status === 'approved'))
        .map((t) => t.id),
    )

  const decide = async (approvalId: number, decision: 'approve' | 'reject') => {
    const a = [...tickets.flatMap((t) => t.approvals), ...loose].find((x) => x.id === approvalId)
    let followUp = false
    setDeciding(approvalId)
    try {
      const out = await api.decide(approvalId, decision)
      say(decision === 'approve'
        ? `Payment sent. Checking is now $${out.payment?.balance_after?.toFixed(2)}. The team will pick the ticket back up.`
        : 'Request rejected. The ticket waits for the next desk run.')
      followUp = decision === 'approve' // a rejection never re-queues the ticket (no loops)
    } catch (e) {
      say((e as Error).message, 'bad')
    } finally {
      setDeciding(null)
      await refresh()
    }
    // The decision unblocks the ticket: the Boss picks it up again to finish or close it,
    // once nothing else on that ticket is waiting for you.
    if (followUp && a?.ticket_id != null) {
      const t = (await api.tickets().catch(() => null))?.tickets.find((x) => x.id === a.ticket_id)
      if (t && t.state === 'open' && !t.approvals.some((x) => x.status === 'pending')) enqueue([t.id])
    }
  }

  const ticket = tickets.find((t) => t.id === selected) ?? null
  const waiting = useMemo(
    () => [...tickets.flatMap((t) => t.approvals), ...loose].filter((a) => a.status === 'pending' || a.status === 'approved'),
    [tickets, loose],
  )
  const last = events.at(-1)
  const active: Actor | null = running !== null && last ? last.agent : null
  const seen = useMemo(() => new Set<string>(events.map((e) => e.agent)), [events])
  const tokens = events.reduce((m, e) => Math.max(m, e.usage?.total_tokens ?? 0), 0)
  const canRun = ticket !== null && ticket.state === 'open' && running === null && !queued.includes(ticket.id)

  return (
    <div className="deck">
      <div className="grid-bg" />
      <header className="topbar">
        <div className="brand">
          <div className="logo">◆</div>
          <div>
            <div className="brand-name">CAMPUS CUSTOMS</div>
            <div className="brand-sub">AGENT COMMAND DECK</div>
          </div>
        </div>
        <div className="telemetry">
          <div className="tele">
            <span>SHOP DATE</span>
            <b>{today || '—'}</b>
          </div>
          <div className="tele">
            <span>LINK</span>
            <b className={online ? 'ok' : 'bad'}>{online ? '● ONLINE' : '● OFFLINE'}</b>
          </div>
          <div className="tele">
            <span>TEAM</span>
            <b>{running !== null ? `WORKING #${running}${queued.length ? ` · next ${queued.map((q) => '#' + q).join(' ')}` : ''}` : 'STANDING BY'}</b>
          </div>
        </div>
        <CashOrb balance={cash?.balance ?? null} asOf={cash?.as_of} />
        <button className="btn desk" onClick={runDesk} disabled={running !== null || !tickets.some((t) => t.state === 'open')}>
          ▶ RUN THE DESK
        </button>
      </header>

      <main className="layout">
        <TicketRail tickets={tickets} selected={selected} running={running} queued={queued} onSelect={setSelected} />

        <section className="panel mission">
          {ticket ? (
            <>
              <div className="mission-head">
                <div>
                  <div className="eyebrow">TICKET #{ticket.id} · {ticket.type.replace('_', ' ').toUpperCase()}</div>
                  <h1>{ticket.subject}</h1>
                  <div className="mission-meta">
                    {ticket.requester}
                    {ticket.sku && ` · ${ticket.qty} × ${ticket.sku} ${ticket.size}`}
                    {ticket.lease_id !== null && ` · lease ${ticket.lease_id}`}
                    {ticket.invoice_id !== null && ` · invoice ${ticket.invoice_id}`}
                  </div>
                </div>
                <div className="mission-side">
                  <span className={`pill big s-${ticket.status}`}>
                    {running === ticket.id ? 'TEAM WORKING' : STATUS_LABEL[ticket.status]}
                  </span>
                  <button className="btn engage" disabled={!canRun} onClick={() => engage(ticket.id)}>
                    {running === ticket.id ? 'TEAM ENGAGED…' : ticket.state === 'resolved' ? 'RESOLVED ✓' : '▶ ENGAGE TEAM'}
                  </button>
                </div>
              </div>

              {ticket.state === 'open' && (
                <div className={`blockers ${ticket.ready_to_close ? 'ready' : ''}`}>
                  {ticket.ready_to_close
                    ? '✓ Everything is done. The Boss will close this ticket on its next run.'
                    : <>To close: {ticket.close_blockers.join(' · ')}</>}
                </div>
              )}

              <div className="mission-body">
                <div className="network">
                  <Constellation active={active} chain={running !== null && last ? last.chain : []} seen={seen} />
                  <div className="now">
                    {active ? (
                      <>
                        <span style={{ color: AGENTS[active].color }}>
                          {AGENTS[active].glyph} {AGENTS[active].label}
                        </span>{' '}
                        is on the line
                      </>
                    ) : running !== null ? (
                      'Boss is reading the desk…'
                    ) : (
                      'Team standing by'
                    )}
                  </div>
                  {tokens > 0 && (
                    <div className="meter" title="tokens used in this run (limit 80,000)">
                      <div style={{ width: `${Math.min(100, (tokens / 80000) * 100)}%` }} />
                      <span>{tokens.toLocaleString()} / 80,000 tokens</span>
                    </div>
                  )}
                </div>
                <div className="channel">
                  <div className="sub-title">
                    {running === ticket.id ? 'LIVE TRANSMISSIONS' : 'TRANSMISSIONS'}
                    {running !== ticket.id && events[0] && <span>last run · {events[0].ts.slice(0, 16).replace('T', ' ')}</span>}
                  </div>
                  <Feed events={events} live={running === ticket.id} />
                </div>
              </div>

              {reply && (
                <div className={`verdict st-${reply.status}`}>
                  <div className="sub-title">BOSS · FINAL CALL · {reply.status.replace('_', ' ').toUpperCase()}</div>
                  <p>{reply.summary}</p>
                  {reply.next_step && <p className="next">Next: {reply.next_step}</p>}
                </div>
              )}

              <div className="sub-title">AGENT DEBRIEF</div>
              <Debrief events={events} />

              {ticket.drafts.length > 0 && (
                <>
                  <div className="sub-title">CUSTOMER DRAFTS · NEVER SENT</div>
                  {ticket.drafts.map((d) => (
                    <div key={d.id} className="draft">
                      <div className="small muted">To {d.recipient} · draft #{d.id}</div>
                      <p>{d.message}</p>
                    </div>
                  ))}
                </>
              )}
            </>
          ) : (
            <div className="muted">{online ? 'Loading the desk…' : 'Start the backend on localhost:8000.'}</div>
          )}
        </section>

        <ApprovalDock approvals={waiting} balance={cash?.balance ?? null} busy={deciding} onDecide={decide} />
      </main>

      {toast && <div className={`toast ${toast.tone}`}>{toast.text}</div>}
    </div>
  )
}
