# Campus Customs Multi-Agent Operation — Harness

## 1. What it is
A team of five PydanticAI agents (Boss, Inventory, Accounting, Facilities, Customer Service) that works the Campus Customs ticket board. Every shop fact and every database change goes through one MCP server (`mcp_server/server.py`) over `data/campus_customs_new.db`. Money moves only after a human approves it. A FastAPI backend (`backend/main.py`) serves a React dashboard (`frontend/`) where the human runs the desk, watches the agents and approves payments.

## 2. How to run it
From `Homework 5/`:
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python backend/run_team.py --ticket 102             # one ticket
python backend/run_team.py --desk --reset           # full run from the command line; resets the working DB first (rule 7)
python backend/approvals.py <approval_id> approve   # the human approves, then the payment runs
cd backend && uvicorn main:app --reload --port 8000  # the API; every start resets the working DB (section 13)
cd frontend && npm run dev                          # the dashboard (section 14)
```
`PORTKEY_API_KEY` is read from `.env` and never printed.

## 3. Architecture
```
React dashboard (frontend/, :5173) ──HTTP──> FastAPI (backend/main.py, :8000)
                                              │
                 run_team.py / main.py ─> agents.py ── 5 PydanticAI agents (gpt-6-luna) ── delegate() handoffs
                                              │  MCP over stdio
                 approvals.py (human only) ───┴──> mcp_server/server.py ──> data/campus_customs_new.db
                 agents.py / approvals.py / main.py ──> audit.py ──> output/audit_trail.json (append-only)
```
- **Shop tools:** only in MCP. The backend has no SQL and no second tools layer.
- **`delegate`:** the one backend tool. It runs another agent and never touches the database.

## 4. Data — `data/campus_customs.db`
- **Original:** `data/campus_customs.db`. Never modified; used to reset.
- **Working copy:** `data/campus_customs_new.db`. The MCP server reads and writes only this file.
- **Reset:** automatic every time the backend starts (`uvicorn main:app …`). It's also available from `POST /api/reset` and `python backend/run_team.py --desk --reset`. Each reset is logged as a `db_reset` audit event.
- **Added tables (working copy only):**
  - `approvals`: payment and PO requests plus the human's decision.
  - `drafts`: customer messages, never sent.

  The server creates both with `CREATE TABLE IF NOT EXISTS`, on start and before every tool call. A reset removes them, and they come back empty on the next call.

| Table | Fields | Why it matters for the agents |
|---|---|---|
| `desk` | `date_today`, `notes` | Master clock: `date_today` is "today" for the shop, so every overdue/due-soon check uses it, never the computer's date; `notes` can carry day-level context. |
| `tickets` | `id`, `type`, `requester`, `subject`, `sku`, `size`, `qty`, `lease_id`, `invoice_id`, `status`, `notes`, `created_at` | The work queue: `type` tells the Boss which agent and tables to use, and `sku`/`size`/`qty`, `lease_id` or `invoice_id` point to the rows the ticket is about; `status` shows open vs. done. |
| `inventory` | `sku`, `name`, `size`, `qty`, `location` | What we physically have, by SKU and size; if stock is short the order can't be filled and Inventory must find a vendor to restock. |
| `pricing` | `sku`, `unit_cost`, `list_price` | Cost vs. selling price per SKU (all sizes share one price), so Accounting can check margins on discounts and purchase orders. |
| `vendors` | `id`, `name`, `specialty`, `lead_days` | Who can restock what (`specialty`) and how many days delivery takes (`lead_days`); a vendor with an open unpaid invoice won't ship. |
| `leases` | `id`, `space_name`, `landlord`, `monthly_rent`, `next_due`, `notes` | The shop space: landlord, monthly rent and `next_due`, which Facilities checks against `desk.date_today` to know when rent must be paid. |
| `cash_accounts` | `name`, `balance`, `date` | How much money we have, as of `date`; every payment comes out of here and the balance can never go negative. |
| `payments` | `id`, `kind`, `ref_id`, `amount`, `account`, `paid_at`, `approved_by` | Ledger of money paid out: `kind` (e.g. rent, invoice), `ref_id` (the lease or invoice id paid), and `approved_by` records the human who approved it. |
| `invoices` | `id`, `vendor_id`, `amount`, `due_date`, `status`, `description` | Bills from vendors with amount, `due_date` and `status`; an open overdue invoice blocks that vendor from shipping until it's paid. |
| `approvals` *(added)* | `id`, `kind`, `ref_id`, `ticket_id`, `vendor_id`, `sku`, `size`, `qty`, `amount`, `reason`, `status`, `requested_by`, `requested_at`, `decided_by`, `decided_at`, `payment_id` | The human-approval queue: agents add `pending` requests, only the human moves them to `approved`/`rejected`, and the pay tool marks them `paid`. |
| `drafts` *(added)* | `id`, `ticket_id`, `recipient`, `message`, `created_by`, `created_at`, `status` | Customer replies kept on the board, never sent (rule 8). |

## 5. Shop rules
1. `desk.date_today` is today; it decides what is overdue.
2. Vendor lead times come from `vendors.lead_days`.
3. A vendor won't ship new product while it has an open unpaid invoice.
4. Every payment (and every purchase order) needs human approval. When something is paid, the related tables are updated.
5. Not enough cash means the pay tool refuses. No negative balances.
6. Cash only goes out; no revenue is modelled.
7. Reset the database to the original before every full run.
8. No real emails or calls; drafts stay on the board.

**Discount policy (ticket 103):** at most 15% off list, and the margin never below $25 per unit. For CC-HOOD-NAVY that means a lowest price of $49.30 and a $27.30 margin. The Boss decides and Accounting checks.

**Ticket statuses:** `open` → `in_progress` → `waiting_approval` → `closed`.

## 6. Models (Pydantic types)
`backend/models.py`:
- **`AgentName`:** `boss | inventory | accounting | facilities | customer_service`.
- **`TeamDeps`:** the acting agent, `run_id`, `ticket_id`, the handoff `chain` (e.g. `boss → facilities → accounting`) and `desk_run`. It is carried into every handoff.
- **`AgentReply`:** what every agent returns:
  - `status`: done / needs_approval / blocked / needs_info
  - `summary`, `ticket_ids`, `approval_ids`, `draft_ids`, `next_step`

  It's checked by the no-invented-facts validator (§10).
- **`AuditEvent`:** one line of the audit trail (§12).

## 7. MCP server and tools
**Server:** `mcp_server/server.py` (FastMCP), shared by every agent over stdio, and the only code that touches `data/campus_customs_new.db`.
- "Today" is `desk.date_today`.
- Tools never invent data: missing rows come back as `found: false` / `ok: false` with a reason.
- The two check tools are plain functions that `get_desk_briefing` reuses, so the briefing's numbers always match theirs.

### Read tools
| Tool | Tables it reads | Ticket it unlocks | Why it's the right tool for that ticket |
|---|---|---|---|
| `list_tickets()` *(problem 7; `ready_to_close` added in problem 9)* | `tickets`, `approvals`, `drafts`, `desk`, plus `invoices`, `inventory` for the close check | **101, 102, 103** (board view) | The dashboard and the Boss see every ticket, open or resolved, with the approval requests and drafts attached, so a ticket already waiting on approval isn't worked twice. |
| `get_desk_briefing(ticket_id=None)` | `desk`, `tickets`, `approvals`, `drafts`, `invoices`, `inventory`; everything else via the two tools below | **101, 102, 103** (Boss triage) | In one call the Boss sees that 101 is blocked by an $840 Bulldog invoice 3 days overdue, 102's $2,400 rent is due in 2 days, and 103 is 12 hoodies short, with $3,240 owed against $3,400 cash, plus any approval already pending, so it can route and prioritise all three. |
| `check_bills_and_cash(lease_id, invoice_id)` | `leases`, `invoices`, `vendors`, `cash_accounts`, `desk`, `approvals` | **102** (also 101's invoice 501) | Ticket 102 only says "rent due in 2 days"; this tool turns `lease_id = 1` into the real amount ($2,400), the due date counted from `desk.date_today` (2026-09-02, 2 days away) and whether checking ($3,400) can cover it, which is everything Facilities and Accounting need before asking a human to approve the payment. |
| `check_stock_and_restock(sku, size, qty_needed)` | `inventory`, `tickets`, `pricing`, `vendors`, `invoices` (vendor hold only), `desk` | **103** (also 101) | Ticket 103 asks for 20 CC-HOOD-NAVY in size M with a discount; this tool shows only 8 on hand, 20 committed to open tickets (projected −12), a $22 cost against a $58 price ($36 margin), the discount floor ($49.30), and which vendors can ship and when. For 101 it shows size S at 0 and Bulldog Print Co not shipping because invoice 501 is unpaid. |

The database doesn't link SKUs to vendors, so the stock tool lists every vendor with its specialty and hold status rather than picking one.

**Added in problem 9 (general rules, worked out from each ticket's fields, never its ID):**
- **Close check (`ready_to_close` + `close_blockers`)** on every ticket, in `get_desk_briefing` and `list_tickets`. A ticket is ready to close when:
  - no approval for it is pending or approved-but-unpaid;
  - its `invoice_id` is paid, and its `lease_id` rent has been paid on this ticket;
  - for product tickets, stock plus paid purchase orders cover `qty` and a customer draft is saved.

  `update_ticket_status(..., "closed")` refuses to close a ticket that isn't ready, and won't touch a ticket that's already closed.
- **`get_desk_briefing(ticket_id)`:** returns just one ticket, about half the size, and lists **all** of that ticket's approvals (pending, approved, paid, rejected), so agents can see what's already been done.
- **Stock already on order:** `check_stock_and_restock` reports `qty_on_order`, `purchase_orders_for_this_item` and `projected_after_open_tickets_and_orders`.
- **No duplicates and no loops:**
  - a purchase order for an item already pending, approved or paid on the ticket is refused;
  - a request the human **rejected** can't be made again on that ticket (same bill, or same item and quantity).
- **Requests link to their ticket:** an invoice or rent request without `ticket_id` is linked to the open ticket that carries that `invoice_id` / `lease_id`. The backend also fills in the ticket being worked.

### Agent write tools (requests and records only; no money moves)
| Tool | Tables | Ticket it unlocks | Why it's the right tool for that ticket |
|---|---|---|---|
| `request_payment_approval(kind, ref_id, reason, ticket_id)` | reads `invoices` or `leases`, `tickets`, `cash_accounts`; writes `approvals` | **101** (invoice 501), **102** (lease 1) | Puts the $840 invoice or the $2,400 rent in front of the human. The amount is read from the database, never typed by an agent, and a second request for the same bill is refused. |
| `request_purchase_order(vendor_id, sku, size, qty, reason, ticket_id)` | reads `vendors`, `inventory`, `pricing`, `invoices`, `tickets`, `desk`, `cash_accounts`; writes `approvals` | **103** (12 hoodies short), **101** (tee S at 0) | Prices the restock at unit cost (12 × $22 = $264), refuses Bulldog while invoice 501 is unpaid (rule 3), and dates arrival from `lead_days` (rule 2). |
| `save_customer_draft(ticket_id, recipient, message)` | reads `tickets`; writes `drafts` | **101** (Tauhid Zaman), **103** (Yale AI Club) | The customer reply stays on the board and is never sent (rule 8). |
| `update_ticket_status(ticket_id, status, note)` | `tickets`, `desk` | **101, 102, 103** | The Boss's final call: moves the ticket through the statuses and appends a dated note saying why. |

### Human-only tools (no agent is given these)
| Tool | Tables | Ticket it unlocks | Why it's the right tool for that ticket |
|---|---|---|---|
| `approve_request(approval_id, decision, decided_by)` | `approvals` | **101, 102** (and any PO for 103) | Records the human's yes or no, and who decided. |
| `pay_approved_payment(approval_id)` | `approvals`, `invoices` or `leases`, `cash_accounts`, `payments`, `desk` | **101** (invoice 501 → `paid`), **102** (rent → `next_due` 2026-10-02) | In one locked transaction it re-checks the human approval and the cash (rule 5), writes `payments` with `approved_by`, lowers checking, and updates the invoice or lease (rule 4). |

## 8. The agents
All five agents use `gpt-6-luna` (reasoning effort low) through Portkey (`backend/agents.py`). Each agent's instructions are `prompts/shop_rules.md` plus its own prompt file.

**Full connectivity:** every agent has `delegate(to_agent, task)`. Agents mostly report back to the Boss, and go peer to peer when that's shorter (e.g. Inventory → Accounting for a PO).

| Agent | Prompt | Job | MCP tools it can use |
|---|---|---|---|
| **Boss** | `prompts/boss.md` | Reads the briefing, ranks tickets, routes them, makes final calls, and is the only one that changes ticket status. | `get_desk_briefing`, `list_tickets`, `check_bills_and_cash`, `check_stock_and_restock`, `update_ticket_status` |
| **Inventory** | `prompts/inventory.md` | Stock on hand, projection after open tickets, shortfall alerts, and a restock vendor chosen by specialty, lead days and hold status. Doesn't order. | `check_stock_and_restock`, `get_desk_briefing` |
| **Accounting** | `prompts/accounting.md` | Cash and bills, margins and the discount floor. Prepares payment and PO requests for the human. Money out only. | `get_desk_briefing`, `check_bills_and_cash`, `check_stock_and_restock`, `request_payment_approval`, `request_purchase_order` |
| **Facilities** | `prompts/facilities.md` | Lease and rent due dates. Hands rent to Accounting and confirms `next_due` moved after payment. | `check_bills_and_cash`, `get_desk_briefing` |
| **Customer Service** | `prompts/customer_service.md` | Owns `customer_order` and `price_override` tickets and writes the customer's reply as a draft. Promises only what tools show. | `get_desk_briefing`, `check_bills_and_cash`, `check_stock_and_restock`, `save_customer_draft` |

**Closing:** the Boss closes a ticket as soon as the briefing says `ready_to_close: true`. A human rejection is final for that run: the Boss notes it, leaves the ticket `in_progress`, and stops.

**Ticket routing** (worked out from the ticket's fields, not its ID, so new tickets route the same way):
- **Names a product** (`sku` set): Inventory first, then Accounting, then Customer Service.
- **About the shop space** (`lease_id` set): Facilities first, then Accounting.
- **Vendor bill only** (`invoice_id` set, no product): Accounting.

## 9. Human approval
- Agents can only **request** approval, which creates an `approvals` row with status `pending`.
- The human decides through `backend/approvals.py`, which the dashboard will call. It calls `approve_request` and then `pay_approved_payment` over the same MCP server, and records `approved_by` as the human (`HUMAN_APPROVER`, default "Inigo Mugica Ortiz").
- No agent's tool list contains the approve or pay tools. `agents.py` asserts this at start-up and checks again on every tool call.
- **Dashboard flow:**
  - **Approve & Pay** pays the request, then queues the ticket so the team can pick it back up and finish or close it.
  - **Reject** records the decision and does **not** queue the ticket, so nothing loops. The ticket waits for the next desk run.
  - Approving again an approval that was approved earlier but refused for lack of cash retries the payment.

## 10. Safety rules
Guardrails a real business would want when agents handle money:
- **Human in the loop:** every payment and PO needs a human click, and agents physically can't approve or pay.
- **Amounts never come from the model:**
  - payment amounts are read from `invoices` / `leases`;
  - PO cost is `qty × pricing.unit_cost`;
  - both are re-read at pay time.
- **Re-check at pay time:** the request must be approved and not already paid, the bill still open, and the cash enough (no negative balance). It all runs in one locked transaction, so it either completes or changes nothing.
- **No duplicates:** a second request for the same invoice or lease, or a second purchase order for an item already on order for the ticket, is refused.
- **Rejections are final:** a request the human rejected can't be re-requested on that ticket, and a rejection never re-queues work.
- **Closing is rule-based:** a ticket closes only when the database shows its bills paid, its stock covered and its draft saved (`ready_to_close`). The tool refuses an early close.
- **Least privilege:**
  - each agent sees only the MCP tools its role needs;
  - write tools stamp the real agent name (`requested_by`, `created_by`, `updated_by`), so an agent can't sign as someone else.
- **No invented facts:**
  - tools validate every ID and return `found/ok = false` instead of guessing;
  - each agent's reply goes through a validator that rejects any `$` amount or ID not seen in a tool result, handoff reply or task in that run (2 retries, then it fails).
- **Nothing leaves the building:** no email or calls; drafts only.
- **Full audit trail** of every step (§12). The original database is never written.
- **Token and loop limits** (§11) keep cost bounded.
- **Provider failures don't crash the desk:** model calls retry up to 4 times on transient errors. If a call still fails, the run stops cleanly with an `error` audit event and a `blocked` reply.
- **Every start is a clean desk:** the backend resets the working database on start (rule 7). The original file is never written.
- **One run at a time:** the API refuses a second concurrent run, and the dashboard queues tickets.

## 11. Specs — model, loop limits, result caps
| Setting | Value |
|---|---|
| Model (all agents) | `gpt-6-luna`, reasoning effort low, via Portkey |
| Budget per ticket run (shared by every agent and handoff in it) | 30 model requests, 35 tool calls, 80,000 tokens (raised from 60k in problem 9 after a run hit the limit) |
| Budget per full desk run | 60 requests, 80 tool calls, 150,000 tokens |
| Handoff depth | 3 (boss → a → b → c). An agent can't delegate to itself or to anyone already in the chain, so loops can't happen. |
| Output retries | 2 per agent run |
| Audit field clip | 2,000 characters per field |
| Model provider retries | 4 (OpenAI client `max_retries`), then the run stops with an `error` event |
| Measured (problem 9) | 8.6k–51.3k tokens per ticket run; 6 runs in total across the three tickets (101: 3, 102: 1, 103: 2) |

If a limit is hit, the run stops, logs `limit_hit`, and returns `blocked` for a human to review.

## 12. Audit trail
- **File:** `output/audit_trail.json`, written by `backend/audit.py`. It's in **JSON Lines** format (one event per line) and only ever opened in append mode, so runs are never wiped.
- **Every line has:** `ts`, `run_id`, `ticket_id`, `agent`, `chain` (the handoff path), `step` (loop step), `event`, `detail`, and `usage` (tokens so far for the whole run).
- **Events:**
  - `run_start`: the task;
  - `model_response`: the tool calls the model asked for, and its text;
  - `mcp_call` / `mcp_result`: tool, arguments, result;
  - `handoff` / `handoff_result`;
  - `output_retry`: amounts or IDs the validator rejected;
  - `limit_hit`, `error` (model provider failure), `run_end` (the final reply), `human_decision`, and `db_reset` (reset on backend start or via the API).

## 13. API reference
`backend/main.py` (FastAPI), started from `backend/` with `uvicorn main:app --reload --port 8000` at http://localhost:8000. **Every start resets the working database** (rule 7). The backend keeps one MCP connection open, so each route answers in about 0.2 s.

- `GET /api/tickets`: returns every ticket and whether it is open or resolved.
- `POST /api/tickets/{ticket_id}/run`: runs the agent team on that ticket.
- `GET /api/events`: returns recent agent events (what each agent said and which tools it used) so the board can refresh.
- `POST /api/approvals/{approval_id}`: the human's Approve click; it pays the approved payment or purchase and updates cash in the database.
- `GET /api/cash`: returns the current checking balance from `cash_accounts`.
- `POST /api/reset`: resets the database to the original values for a fresh run. The dashboard has no button for it any more, because the backend resets on start.

## 14. Dashboard (front end)
- **Folder:** `frontend/` (React + Vite + TypeScript).
- **Start:** from `frontend/`, run `npm install` once, then `npm run dev`. It opens http://localhost:5173.
- **Backend:** it calls the backend at http://localhost:8000 (`VITE_API_URL`), which allows this origin via CORS.
- **What it does:**
  - shows every ticket;
  - starts the team on a picked ticket and streams which agent is acting and what it says or does (polling `/api/events`);
  - shows the Boss's final call and a per-agent debrief;
  - marks tickets RESOLVED when the Boss closes them;
  - lets the human approve or reject payments and POs;
  - shows the checking balance, which counts down after an approved payment.
- **Added in problem 9:**
  - **▶ RUN THE DESK** queues every open ticket that isn't waiting on the human; runs go one at a time.
  - Queued tickets show a dashed **QUEUED · n** pill.
  - Approving a payment automatically queues that ticket again.
  - Closed tickets move to a **CLOSED TICKETS** section.
  - Each open ticket shows **"To close: …"**, the list of its `close_blockers`, which turns green when it's ready.
  - `?ticket=ID` opens the dashboard on a ticket; the problem 9 screenshots use it.
  - The Reset button was removed.
- **Design:** layout and choices are in `output/design.md`.

## 15. Verification log
- **Problem 3:** the three read tools were tested in memory and matched the database.
- **Problem 4:** `output/mcp_smoke.json` holds the three tools called over real MCP, with values cross-checked against the database.
- **Problem 5, MCP write tools** (run over stdio, then the database was reset):
  - a rent request was approved and paid: checking went $3,400 → $1,000 and `next_due` moved 2026-09-02 → 2026-10-02;
  - the invoice was paid: 501 became `paid` and checking went to $160;
  - a PO to Bulldog was refused (invoice 501 open);
  - a $264 PO was refused at pay time with only $160 in checking;
  - a duplicate request, paying before approval, paying twice, an unknown ticket and a bad status were all refused.
- **Problem 5, per-agent tools:** each agent's visible tools match §8, and no agent sees `approve_request` or `pay_approved_payment`.
- **Problem 5, live run on ticket 102:**
  - the chain went boss → facilities → accounting;
  - approval request 1 ($2,400 rent) was created as `pending`;
  - ticket 102 went to `waiting_approval`;
  - no payment was made;
  - about 23.6k tokens were used;
  - 30 audit lines were written.

  The database was reset afterwards.
- **Note on `output/audit_trail.json`:** the file is append-only, so it keeps the problem 5 test lines. The **first line** is a `run_start` for ticket 102 with no matching `run_end`. That attempt crashed on a logging bug in `agents.py` (`run.usage()` called as a function), which was then fixed. It made no tool calls and no database changes. The next 30 lines are the successful ticket 102 test run.
- **Problem 9, resolving the tickets** (human run on the dashboard, 2026-10-14):
  - **Start:** the backend start reset the database at 19:38:27. Checking was **$3,400.00**, all three tickets open, no approvals, no payments.
  - **Human decisions:**
    - approval 1, invoice 501, $840.00: approved;
    - approval 2, rent for lease 1, $2,400.00: approved;
    - approval 3, 12-hoodie PO, $264.00: **rejected**;
    - approval 4, 1-tee PO, $8.00: approved.
  - **Results:**
    - **101** closed after 3 runs;
    - **102** closed after 1 run;
    - **103** stayed `in_progress`: 12 hoodies are not covered after the rejection, and it waits for the next desk run.
  - **Cash:** $3,400.00 − $840.00 − $2,400.00 − $8.00 = **$152.00**, which matches `cash_accounts`. A script cross-checked every amount in `desk_tickets.html` (Cash tab) and `resolved_tickets.json` against the `payments` and `approvals` tables.
  - **Outputs:**
    - `desk_tickets.html`: Actual sections and Cash tab filled; Expected sections verified byte-identical to before;
    - `resolved_tickets.json`: one JSON line per ticket;
    - `resolved_board.html`: one dashboard screenshot per ticket, taken with headless Edge from `http://localhost:5173/?ticket=ID`;
    - `audit_trail.json`: the real runs appended.
  - **Earlier attempts in the audit trail.** The working database was reset before each attempt. Each failure led to a general fix:
    1. Accounting checked invoice 501 but never requested approval, while the Boss set `waiting_approval` anyway. Fix: Accounting must create the request, and the Boss may set `waiting_approval` only when an approval ID exists.
    2. The $8 tee PO was requested twice, because paid approvals weren't visible to the agents. Also, the rent request had no `ticket_id`, and a run hit the 60k-token limit. Fix:
       - per-ticket briefing showing all approvals;
       - stock on order counted;
       - duplicate POs refused;
       - requests auto-linked to their ticket;
       - limit raised to 80k.
    3. A ticket 103 run crashed on a model-provider error (HTTP 500), and queued follow-ups looked frozen. Fix: provider retries and clean error handling; queued pills on the dashboard.
    4. Paid tickets never closed: the Boss read 102's moved `next_due` as a conflict. A rejected PO could also be re-requested. Fix: the rule-based `ready_to_close`, a close tool that refuses early closes, final rejections, and Reject not re-queuing.
