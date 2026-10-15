// Shapes returned by the FastAPI routes (backend/main.py).

export type AgentName = 'boss' | 'inventory' | 'accounting' | 'facilities' | 'customer_service'
export type Actor = AgentName | 'human' | 'system'

export interface Approval {
  id: number
  kind: 'invoice' | 'rent' | 'purchase_order'
  ref_id: number | null
  ticket_id: number | null
  vendor_id: number | null
  sku: string | null
  size: string | null
  qty: number | null
  amount: number
  reason: string | null
  status: 'pending' | 'approved' | 'rejected' | 'paid'
  requested_by: string
  requested_at: string
  decided_by: string | null
  decided_at: string | null
  payment_id: number | null
}

export interface Draft {
  id: number
  ticket_id: number
  recipient: string
  message: string
  created_by: string
  created_at: string
  status: string
}

export interface Ticket {
  id: number
  type: string
  requester: string
  subject: string
  sku: string | null
  size: string | null
  qty: number | null
  lease_id: number | null
  invoice_id: number | null
  status: 'open' | 'in_progress' | 'waiting_approval' | 'closed'
  state: 'open' | 'resolved'
  notes: string | null
  created_at: string
  approvals: Approval[]
  drafts: Draft[]
  ready_to_close: boolean
  close_blockers: string[]
  rejected_approvals: number[]
}

export interface TicketsResponse {
  today: string
  tickets: Ticket[]
  approvals_without_ticket: Approval[]
}

export interface Cash {
  account: string
  balance: number
  as_of: string
  today: string
}

export interface AgentReply {
  status: 'done' | 'needs_approval' | 'blocked' | 'needs_info'
  summary: string
  ticket_ids: number[]
  approval_ids: number[]
  draft_ids: number[]
  next_step: string | null
}

export interface AgentEvent {
  line: number
  ts: string
  run_id: string
  ticket_id: number | null
  agent: Actor
  chain: string[]
  step: number | null
  event: string
  detail: Record<string, unknown>
  usage: { total_tokens: number; requests: number; tool_calls: number } | null
}

export interface EventsResponse {
  next: number
  events: AgentEvent[]
}
