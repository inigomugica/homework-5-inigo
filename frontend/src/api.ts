// Thin client for the problem 7 routes. The backend runs on localhost:8000.
import type { AgentReply, Cash, EventsResponse, TicketsResponse } from './types'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error(body.detail ?? `${r.status} ${r.statusText}`)
  }
  return r.json() as Promise<T>
}

export const api = {
  tickets: () => req<TicketsResponse>('/api/tickets'),
  runTicket: (id: number) =>
    req<{ ticket_id: number; run_id: string; reply: AgentReply }>(`/api/tickets/${id}/run`, { method: 'POST' }),
  events: (params: { after?: number; limit?: number; ticket_id?: number }) => {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => v !== undefined && q.set(k, String(v)))
    return req<EventsResponse>(`/api/events?${q}`)
  },
  decide: (approvalId: number, decision: 'approve' | 'reject') =>
    req<{ decision: unknown; payment?: { ok: boolean; balance_after?: number } }>(`/api/approvals/${approvalId}`, {
      method: 'POST',
      body: JSON.stringify({ decision }),
    }),
  cash: () => req<Cash>('/api/cash'),
}
