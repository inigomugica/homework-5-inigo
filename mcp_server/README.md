# Campus Customs MCP server

**What it's for:** the one shared toolbox for every agent on the Campus Customs team (Boss, Inventory, Accounting, Facilities, Customer Service). Agents get shop facts and make changes only through these tools; nothing else touches the database. So every agent sees the same numbers, and the money rules are enforced in one place.

**Database:** `../data/campus_customs_new.db`, the working copy. The original `data/campus_customs.db` is never opened and is kept for resets. On start, and before any tool call after a reset, the server adds two tables to the working copy if they're missing: `approvals` and `drafts`. "Today" always comes from `desk.date_today`.

**Built with:** FastMCP (`server.py`). Tools return only what's in the database plus simple arithmetic, and say `found: false` / `ok: false` instead of guessing. Agents never supply money amounts; tools read them from the database.

## Tools

**Read**
| Tool | What it returns |
|---|---|
| `list_tickets()` | Every ticket (open and closed) with an open/resolved flag, its approval requests and drafts, and the close check (`ready_to_close`, `close_blockers`). Used by the dashboard and the Boss. |
| `get_desk_briefing(ticket_id=None)` | Today's date, desk notes, each open ticket (or just `ticket_id`) with its stock and/or bill facts, **all** its approvals and drafts, the close check, approval requests in progress, total open bills and cash. |
| `check_bills_and_cash(lease_id=None, invoice_id=None)` | Rent and vendor invoices: amount, payee, days until due (negative = overdue), any approval request, and whether cash covers them. |
| `check_stock_and_restock(sku, size, qty_needed)` | Qty on hand, shortfall, qty committed to open tickets, qty already on order (purchase orders) and the projections after them, cost / price / margin, the discount floor, and each vendor's lead days, arrival date, unpaid invoices and whether it will ship. |

**Agent write tools (no money moves)**
| Tool | What it does |
|---|---|
| `request_payment_approval(kind, ref_id, requested_by, reason, ticket_id=None)` | Queues an invoice or rent payment for human approval. The amount comes from the database. Duplicates and requests the human already rejected are refused. A missing `ticket_id` is linked to the open ticket for that bill. |
| `request_purchase_order(vendor_id, sku, size, qty, requested_by, reason, ticket_id=None)` | Queues a restock PO at unit cost for human approval. Refuses vendors with an open unpaid invoice, items already on order for the ticket, and POs the human already rejected. |
| `save_customer_draft(ticket_id, recipient, message, created_by)` | Saves a customer message as a draft. It is never sent. |
| `update_ticket_status(ticket_id, status, note, updated_by)` | Sets `open` / `in_progress` / `waiting_approval` / `closed` and appends a dated note. Refuses to close a ticket that isn't `ready_to_close`, or to change one that's already closed. |

**Human only (the backend's approval path calls these; no agent is given them)**
| Tool | What it does |
|---|---|
| `approve_request(approval_id, decision, decided_by)` | Records the human's approve or reject. |
| `pay_approved_payment(approval_id)` | Pays an approved request in one transaction. It re-checks the approval and the cash (never negative), writes `payments`, lowers the balance, and marks the invoice paid or moves the lease's `next_due` forward one month. |

## Run

From the `Homework 5` folder:

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python mcp_server/server.py
```
