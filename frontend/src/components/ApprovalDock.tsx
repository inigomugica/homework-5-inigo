import { AGENTS, money } from '../agents'
import type { Actor, Approval } from '../types'

const KIND: Record<Approval['kind'], string> = {
  invoice: 'Vendor invoice',
  rent: 'Rent',
  purchase_order: 'Purchase order',
}

/** Requests the agents prepared. Only a human click here moves money. */
export function ApprovalDock({ approvals, balance, busy, onDecide }: {
  approvals: Approval[]
  balance: number | null
  busy: number | null
  onDecide: (id: number, d: 'approve' | 'reject') => void
}) {
  return (
    <section className="panel dock">
      <h2 className="panel-title">
        AUTHORIZATION <span>{approvals.length} waiting</span>
      </h2>
      {approvals.length === 0 && (
        <div className="muted small">Nothing needs your signature. Agents can request, never pay.</div>
      )}
      {approvals.map((a) => {
        const after = balance === null ? null : balance - a.amount
        const short = after !== null && after < 0
        const who = AGENTS[a.requested_by as Actor]
        return (
          <div key={a.id} className={`auth ${short ? 'short' : ''}`}>
            <div className="auth-top">
              <span className="auth-kind">
                {KIND[a.kind]}
                {a.ticket_id ? ` · #${a.ticket_id}` : ''}
              </span>
              <span className="auth-amt">{money(a.amount)}</span>
            </div>
            {a.kind === 'purchase_order' && (
              <div className="small">
                {a.qty} × {a.sku} {a.size}
              </div>
            )}
            {a.reason && <div className="auth-reason">“{a.reason}”</div>}
            <div className="auth-meta">
              requested by <b style={{ color: who?.color }}>{who?.label ?? a.requested_by}</b>
              {after !== null && (
                <>
                  {' '}· after: <b className={short ? 'bad' : ''}>{short ? 'not enough cash' : money(after)}</b>
                </>
              )}
              {a.status === 'approved' && (
                <>
                  {' '}· <b className="warn">approved, payment refused earlier</b>
                </>
              )}
            </div>
            <div className="auth-actions">
              <button className="btn approve" disabled={busy !== null} onClick={() => onDecide(a.id, 'approve')}>
                {busy === a.id ? 'AUTHORIZING…' : a.status === 'approved' ? 'RETRY PAYMENT' : 'APPROVE & PAY'}
              </button>
              {a.status === 'pending' && (
                <button className="btn ghost" disabled={busy !== null} onClick={() => onDecide(a.id, 'reject')}>
                  REJECT
                </button>
              )}
            </div>
          </div>
        )
      })}
    </section>
  )
}
