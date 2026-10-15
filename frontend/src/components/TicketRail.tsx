import { STATUS_LABEL } from '../agents'
import type { Ticket } from '../types'

const TYPE_LABEL: Record<string, string> = {
  customer_order: 'Customer order',
  rent_notice: 'Rent notice',
  price_override: 'Price override',
}

export function TicketRail({ tickets, selected, running, queued, onSelect }: {
  tickets: Ticket[]
  selected: number | null
  running: number | null
  queued: number[]
  onSelect: (id: number) => void
}) {
  const open = tickets.filter((t) => t.state === 'open')
  const closed = tickets.filter((t) => t.state === 'resolved')
  return (
    <aside className="panel rail">
      <h2 className="panel-title">
        TICKET BOARD <span>{open.length} open</span>
      </h2>
      {open.length === 0 && <div className="muted small">Desk is clear. Every ticket is resolved.</div>}
      <TicketList tickets={open} selected={selected} running={running} queued={queued} onSelect={onSelect} />
      {closed.length > 0 && (
        <>
          <h2 className="panel-title closed-title">
            CLOSED TICKETS <span>{closed.length}</span>
          </h2>
          <TicketList tickets={closed} selected={selected} running={running} queued={queued} onSelect={onSelect} />
        </>
      )}
    </aside>
  )
}

function TicketList({ tickets, selected, running, queued, onSelect }: {
  tickets: Ticket[]
  selected: number | null
  running: number | null
  queued: number[]
  onSelect: (id: number) => void
}) {
  return (
      <div className="rail-list">
        {tickets.map((t) => {
          const waiting = t.approvals.filter((a) => a.status === 'pending' || a.status === 'approved').length
          return (
            <button
              key={t.id}
              className={`ticket s-${t.status} ${selected === t.id ? 'sel' : ''} ${running === t.id ? 'live' : ''} ${queued.includes(t.id) ? 'queued' : ''}`}
              onClick={() => onSelect(t.id)}
            >
              <div className="ticket-top">
                <span className="ticket-id">#{t.id}</span>
                <span className="pill">{running === t.id ? 'TEAM WORKING' : queued.includes(t.id) ? `QUEUED · ${queued.indexOf(t.id) + 1}` : STATUS_LABEL[t.status]}</span>
              </div>
              <div className="ticket-subject">{t.subject}</div>
              <div className="ticket-meta">
                {TYPE_LABEL[t.type] ?? t.type} · {t.requester}
              </div>
              {(waiting > 0 || t.drafts.length > 0) && (
                <div className="ticket-flags">
                  {waiting > 0 && <span className="flag gold">◉ {waiting} approval{waiting > 1 ? 's' : ''}</span>}
                  {t.drafts.length > 0 && (
                    <span className="flag pink">✦ {t.drafts.length} draft{t.drafts.length > 1 ? 's' : ''}</span>
                  )}
                </div>
              )}
              {t.state === 'resolved' && <div className="stamp">RESOLVED</div>}
            </button>
          )
        })}
      </div>
  )
}
