// How each agent looks on the deck: a colour, a glyph, a call sign and a role line.
import type { Actor, AgentEvent, Ticket } from './types'

export interface AgentMeta {
  label: string
  callsign: string
  role: string
  color: string
  glyph: string
}

export const AGENTS: Record<Actor, AgentMeta> = {
  boss: { label: 'Boss', callsign: 'COMMAND', role: 'Routes tickets · final call', color: '#ffc94d', glyph: '◆' },
  inventory: { label: 'Inventory', callsign: 'STOCK', role: 'Stock · shortfalls · restock', color: '#38e8ff', glyph: '▣' },
  accounting: { label: 'Accounting', callsign: 'LEDGER', role: 'Cash · bills · approvals', color: '#4dffa6', glyph: '$' },
  facilities: { label: 'Facilities', callsign: 'SPACE', role: 'Lease · rent', color: '#b28cff', glyph: '⌂' },
  customer_service: { label: 'Customer Service', callsign: 'VOICE', role: 'Customer drafts', color: '#ff6fb5', glyph: '✦' },
  human: { label: 'You', callsign: 'HUMAN', role: 'Approves payments', color: '#f2f5ff', glyph: '●' },
  system: { label: 'System', callsign: 'SYS', role: '', color: '#7d8aa8', glyph: '·' },
}

export const TEAM: Actor[] = ['boss', 'inventory', 'accounting', 'facilities', 'customer_service']

const TOOL_WORDS: Record<string, string> = {
  get_desk_briefing: 'reads the desk briefing',
  list_tickets: 'scans the ticket board',
  check_bills_and_cash: 'checks bills and cash',
  check_stock_and_restock: 'checks stock and restock options',
  request_payment_approval: 'requests a payment approval',
  request_purchase_order: 'requests a purchase order',
  save_customer_draft: 'saves a customer draft',
  update_ticket_status: 'updates the ticket status',
  approve_request: 'records the approval',
  pay_approved_payment: 'pays the approved request',
}

const short = (v: unknown, n = 140) => {
  const s = typeof v === 'string' ? v : JSON.stringify(v)
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}

const name = (a: unknown) => AGENTS[(a as Actor) ?? 'system']?.label ?? String(a)

/** One readable line for the transmission feed, or null for events we don't show. */
export function describe(e: AgentEvent): { verb: string; text: string; tone?: 'ok' | 'warn' | 'bad' } | null {
  const d = e.detail as Record<string, any>
  switch (e.event) {
    case 'run_start':
      return { verb: 'ONLINE', text: short(d.task, 180) }
    case 'model_response': {
      const calls = (d.tool_calls as { tool: string }[]) ?? []
      if (d.text) return { verb: 'SAYS', text: short(d.text, 180) }
      if (calls.some((c) => c.tool === 'final_result')) return { verb: 'THINKS', text: 'composing its report' }
      return null // the tool call itself is logged next as mcp_call / handoff
    }
    case 'mcp_call':
      return { verb: 'TOOL', text: TOOL_WORDS[d.tool] ?? d.tool }
    case 'mcp_result': {
      const r = typeof d.result === 'string' ? safeJson(d.result) : d.result
      const bad = r && (r.ok === false || r.found === false)
      return bad ? { verb: 'REFUSED', text: short(r.error ?? 'refused'), tone: 'warn' } : null
    }
    case 'handoff':
      return { verb: 'HANDOFF', text: `→ ${name(d.to)}: ${short(d.task, 150)}` }
    case 'handoff_result':
      return { verb: 'RECEIVED', text: `report from ${name(d.from)}` }
    case 'output_retry':
      return { verb: 'CHECK', text: 'fact check rejected an unverified number; retrying', tone: 'warn' }
    case 'limit_hit':
      return { verb: 'LIMIT', text: short(d.error), tone: 'bad' }
    case 'error':
      return { verb: 'ERROR', text: short(d.error), tone: 'bad' }
    case 'run_end': {
      const reply = d.reply as { status?: string; summary?: string } | undefined
      if (!reply) return { verb: 'DONE', text: short(d.action ?? 'done') }
      return { verb: (reply.status ?? 'done').toUpperCase().replace('_', ' '), text: short(reply.summary, 220), tone: 'ok' }
    }
    case 'human_decision':
      return { verb: 'DECISION', text: `approval #${d.approval_id} by ${d.decided_by}` }
    default:
      return null
  }
}

function safeJson(s: string) {
  try {
    return JSON.parse(s)
  } catch {
    return null
  }
}

export const money = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 })

export const STATUS_LABEL: Record<Ticket['status'], string> = {
  open: 'OPEN',
  in_progress: 'IN PROGRESS',
  waiting_approval: 'AWAITING APPROVAL',
  closed: 'RESOLVED',
}
