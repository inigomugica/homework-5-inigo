"""Campus Customs MCP server.

The only way any agent reads or changes the shop. Every fact comes from the
working database; tools do simple arithmetic on it (days until due,
shortfall, margin, cost) and never invent data. Anything missing comes back
as found=false / ok=false with a reason.

Read tools:  get_desk_briefing, check_bills_and_cash, check_stock_and_restock, list_tickets
Agent write tools (requests and records only, no money moves):
             request_payment_approval, request_purchase_order,
             save_customer_draft, update_ticket_status
Human-only tools (the backend calls these when the human clicks Approve;
no agent is given them): approve_request, pay_approved_payment

Run: python mcp_server/server.py   (stdio; see .mcp.json)
"""

import calendar
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP

# Working copy only. The original data/campus_customs.db is never opened.
DB_PATH = Path(__file__).resolve().parents[1] / "data" / "campus_customs_new.db"
PAY_FROM_ACCOUNT = "checking"

# Discount policy for price_override tickets (documented in output/harness.md).
MAX_DISCOUNT_PCT = 15.0
MIN_MARGIN_PER_UNIT = 25.0

TICKET_STATUSES = ("open", "in_progress", "waiting_approval", "closed")

mcp = FastMCP("campus-customs")
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False}
WRITES = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False}
MOVES_MONEY = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False}

# Added to the working copy only. A reset (copying the original back) removes
# them; they are recreated, empty, the next time the server starts.
NEW_TABLES = """
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,              -- invoice | rent | purchase_order
    ref_id INTEGER,                  -- invoices.id or leases.id (NULL for purchase_order)
    ticket_id INTEGER,
    vendor_id INTEGER, sku TEXT, size TEXT, qty INTEGER,   -- purchase_order only
    amount REAL NOT NULL,            -- always read from the database, never from an agent
    reason TEXT,
    status TEXT NOT NULL,            -- pending | approved | rejected | paid
    requested_by TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    decided_by TEXT, decided_at TEXT,
    payment_id INTEGER
);
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    recipient TEXT NOT NULL,
    message TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'   -- never sent (shop rule 8)
);
"""


def _connect(write: bool = False) -> sqlite3.Connection:
    _ensure_tables_once()
    mode = "rw" if write else "ro"
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode={mode}", uri=True)
    con.row_factory = sqlite3.Row
    return con


def ensure_tables() -> None:
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=rw", uri=True)
    with closing(con):
        con.executescript(NEW_TABLES)


def _ensure_tables_once() -> None:
    """Recreate the added tables if a reset removed them while this server was running."""
    con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    with closing(con):
        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not {"approvals", "drafts"} <= have:
        ensure_tables()


def _today(con: sqlite3.Connection) -> date:
    """Shop rule 1: desk.date_today is "today", not the computer's clock."""
    return date.fromisoformat(con.execute("SELECT date_today FROM desk").fetchone()["date_today"])


def _days_until(due: str, today: date) -> int:
    return (date.fromisoformat(due) - today).days


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _add_month(d: date) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _cash(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT name, balance, date FROM cash_accounts")]


def _balance(con: sqlite3.Connection, account: str = PAY_FROM_ACCOUNT) -> float | None:
    r = con.execute("SELECT balance FROM cash_accounts WHERE name = ?", (account,)).fetchone()
    return None if r is None else r["balance"]


def _open_invoices_for_vendor(con: sqlite3.Connection, vendor_id: int, today: date) -> list[dict]:
    rows = con.execute(
        "SELECT id, amount, due_date, description FROM invoices WHERE vendor_id = ? AND status = 'open'",
        (vendor_id,),
    )
    return [{**dict(r), "days_until_due": _days_until(r["due_date"], today)} for r in rows]


def _ticket_for(con: sqlite3.Connection, kind: str, ref_id: int) -> int | None:
    """The open ticket a bill belongs to (lease_id / invoice_id on the ticket), if exactly one."""
    col = "lease_id" if kind == "rent" else "invoice_id"
    rows = con.execute(f"SELECT id FROM tickets WHERE {col} = ? AND status != 'closed'", (ref_id,)).fetchall()
    return rows[0]["id"] if len(rows) == 1 else None


def _active_approval(con: sqlite3.Connection, kind: str, ref_id: int) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM approvals WHERE kind = ? AND ref_id = ? AND status IN ('pending', 'approved')",
        (kind, ref_id),
    ).fetchone()


# --- Plain functions (shared by the tools and by the briefing) ---------------


def closure_check(con: sqlite3.Connection, t: sqlite3.Row | dict) -> dict:
    """Is this ticket's work finished? Fixed rules on database facts, so the
    Boss doesn't have to judge it (and can't loop on it):
      - no approval for the ticket is still pending or approved-but-unpaid
      - a linked invoice is paid; a linked lease has a paid rent approval on this ticket
      - a product ticket's quantity is covered by stock or by paid purchase orders,
        and a customer draft is saved
    A rejected request is final for this run: it never counts as done and is never re-requested."""
    tid = t["id"]
    approvals = con.execute("SELECT id, kind, status FROM approvals WHERE ticket_id = ?", (tid,)).fetchall()
    blockers, rejected = [], [a["id"] for a in approvals if a["status"] == "rejected"]
    waiting = [a["id"] for a in approvals if a["status"] in ("pending", "approved")]
    if waiting:
        blockers.append(f"approval(s) {waiting} still waiting for the human or for payment")
    if t["invoice_id"] is not None:
        inv = con.execute("SELECT status FROM invoices WHERE id = ?", (t["invoice_id"],)).fetchone()
        if inv is None or inv["status"] != "paid":
            blockers.append(f"invoice {t['invoice_id']} is not paid")
    if t["lease_id"] is not None and not any(a["kind"] == "rent" and a["status"] == "paid" for a in approvals):
        blockers.append(f"rent for lease {t['lease_id']} has not been paid on this ticket")
    if t["sku"] and t["size"]:
        inv_row = con.execute("SELECT qty FROM inventory WHERE sku = ? AND size = ?", (t["sku"], t["size"])).fetchone()
        on_hand = inv_row["qty"] if inv_row else 0
        ordered = con.execute(
            "SELECT COALESCE(SUM(qty), 0) AS q FROM approvals WHERE ticket_id = ? AND kind = 'purchase_order' "
            "AND sku = ? AND size = ? AND status = 'paid'", (tid, t["sku"], t["size"])).fetchone()["q"]
        if on_hand + ordered < (t["qty"] or 0):
            blockers.append(f"{t['qty']} needed but only {on_hand} on hand + {ordered} on paid order")
        if con.execute("SELECT 1 FROM drafts WHERE ticket_id = ?", (tid,)).fetchone() is None:
            blockers.append("no customer draft saved yet")
    return {"ready_to_close": not blockers, "close_blockers": blockers, "rejected_approvals": rejected}


def bills_and_cash(lease_id: int | None = None, invoice_id: int | None = None) -> dict:
    with closing(_connect()) as con:
        today = _today(con)
        bills = []

        if invoice_id is not None or lease_id is None:
            q = """SELECT i.id, i.amount, i.due_date, i.status, i.description,
                          v.id AS vendor_id, v.name AS vendor_name
                   FROM invoices i JOIN vendors v ON v.id = i.vendor_id"""
            if invoice_id is not None:
                rows = con.execute(q + " WHERE i.id = ?", (invoice_id,)).fetchall()
                if not rows:
                    return {"found": False, "error": f"Invoice {invoice_id} not found."}
            else:
                rows = con.execute(q + " WHERE i.status = 'open'").fetchall()
            for r in rows:
                bills.append({
                    "kind": "invoice", "id": r["id"], "payee": r["vendor_name"],
                    "vendor_id": r["vendor_id"], "amount": r["amount"], "due_date": r["due_date"],
                    "days_until_due": _days_until(r["due_date"], today),
                    "status": r["status"], "description": r["description"],
                })

        if lease_id is not None or invoice_id is None:
            q = "SELECT id, space_name, landlord, monthly_rent, next_due, notes FROM leases"
            if lease_id is not None:
                rows = con.execute(q + " WHERE id = ?", (lease_id,)).fetchall()
                if not rows:
                    return {"found": False, "error": f"Lease {lease_id} not found."}
            else:
                rows = con.execute(q).fetchall()
            for r in rows:
                bills.append({
                    "kind": "rent", "id": r["id"], "payee": r["landlord"],
                    "space_name": r["space_name"], "amount": r["monthly_rent"],
                    "due_date": r["next_due"], "days_until_due": _days_until(r["next_due"], today),
                    "notes": r["notes"],
                })

        for b in bills:
            b["overdue"] = b["days_until_due"] < 0
            a = _active_approval(con, b["kind"], b["id"])
            b["approval_request"] = None if a is None else {"id": a["id"], "status": a["status"]}

        cash = _cash(con)
        unpaid = [b for b in bills if b.get("status", "open") == "open"]
        total_due = sum(b["amount"] for b in unpaid)
        return {
            "found": True,
            "today": today.isoformat(),
            "bills": bills,
            "total_due": total_due,
            "cash_accounts": cash,
            "accounts_that_can_cover_total": [a["name"] for a in cash if a["balance"] >= total_due],
        }


def stock_and_restock(sku: str, size: str, qty_needed: int) -> dict:
    with closing(_connect()) as con:
        today = _today(con)
        item = con.execute(
            "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? AND size = ?",
            (sku, size),
        ).fetchone()
        if item is None:
            sizes = [r["size"] for r in con.execute("SELECT size FROM inventory WHERE sku = ?", (sku,))]
            return {"found": False, "error": f"No inventory row for {sku} size {size}.",
                    "sizes_on_file_for_sku": sizes}

        committed = con.execute(
            "SELECT id, qty FROM tickets WHERE sku = ? AND size = ? AND status != 'closed'",
            (sku, size),
        ).fetchall()
        committed_qty = sum(r["qty"] or 0 for r in committed)
        orders = [dict(r) for r in con.execute(
            "SELECT id, ticket_id, vendor_id, qty, amount, status FROM approvals "
            "WHERE kind = 'purchase_order' AND sku = ? AND size = ? AND status IN ('pending', 'approved', 'paid')",
            (sku, size))]
        on_order = sum(o["qty"] for o in orders)

        price = con.execute("SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (sku,)).fetchone()
        pricing = None
        if price is not None:
            cost, lst = price["unit_cost"], price["list_price"]
            floor = round(max(lst * (1 - MAX_DISCOUNT_PCT / 100), cost + MIN_MARGIN_PER_UNIT), 2)
            pricing = {
                "unit_cost": cost, "list_price": lst,
                "margin_per_unit": lst - cost,
                "margin_pct_of_list": round(100 * (lst - cost) / lst, 1),
                "discount_policy": f"max {MAX_DISCOUNT_PCT:g}% off list, margin never below ${MIN_MARGIN_PER_UNIT:g}/unit",
                "lowest_allowed_unit_price": floor,
                "margin_at_lowest_price": round(floor - cost, 2),
                "restock_cost_per_unit": cost,
            }

        vendors = []
        for v in con.execute("SELECT id, name, specialty, lead_days FROM vendors"):
            open_inv = _open_invoices_for_vendor(con, v["id"], today)
            vendors.append({
                **dict(v),
                "open_unpaid_invoices": open_inv,
                "will_ship": not open_inv,  # shop rule 3
                "earliest_arrival_if_ordered_today": date.fromordinal(today.toordinal() + v["lead_days"]).isoformat(),
            })

        return {
            "found": True,
            "today": today.isoformat(),
            "sku": item["sku"], "name": item["name"], "size": item["size"],
            "location": item["location"],
            "qty_on_hand": item["qty"], "qty_needed": qty_needed,
            "shortfall": max(0, qty_needed - item["qty"]),
            "committed_to_open_tickets": committed_qty,
            "open_ticket_ids_for_this_item": [r["id"] for r in committed],
            "projected_after_open_tickets": item["qty"] - committed_qty,
            "purchase_orders_for_this_item": orders,   # pending, approved or paid (paid = ordered, not yet arrived)
            "qty_on_order": on_order,
            "projected_after_open_tickets_and_orders": item["qty"] + on_order - committed_qty,
            "pricing": pricing,
            "vendors": vendors,
            "note": "The database does not link SKUs to vendors; choose by specialty.",
        }


# --- Read tools --------------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
def check_bills_and_cash(lease_id: int | None = None, invoice_id: int | None = None) -> dict:
    """Admin side: rent and vendor invoices against cash.

    Pass a lease_id or invoice_id for one bill, or nothing for every open
    invoice and every lease's next rent. Returns amount, payee, due date,
    days until due (negative = overdue, measured from desk.date_today),
    any existing approval request, the cash accounts, and which accounts can
    cover the total. Read-only; it never pays anything.
    """
    return bills_and_cash(lease_id, invoice_id)


@mcp.tool(annotations=READ_ONLY)
def check_stock_and_restock(sku: str, size: str, qty_needed: int) -> dict:
    """Product side: stock, projection, margin and restock options for one SKU and size.

    Returns qty on hand, shortfall versus qty_needed, qty committed to open
    tickets and the projected stock after them, unit cost / list price /
    margin, the discount policy with the lowest allowed unit price, and every
    vendor with specialty, lead days, earliest arrival, open unpaid invoices
    and whether it will ship. Read-only.
    """
    return stock_and_restock(sku, size, qty_needed)


@mcp.tool(annotations=READ_ONLY)
def get_desk_briefing(ticket_id: int | None = None) -> dict:
    """The Boss's view: today's date, desk notes, each open ticket with the
    facts that block or unblock it, ALL its approval requests (pending,
    approved, paid, rejected) and drafts, plus the cash position.

    Pass ticket_id to get just that ticket (much smaller; use it when working
    one ticket). Built from the two check tools, so the numbers match theirs.
    """
    with closing(_connect()) as con:
        desk = dict(con.execute("SELECT date_today, notes FROM desk").fetchone())
        q = "SELECT * FROM tickets WHERE status != 'closed'"
        tickets = [dict(r) for r in (con.execute(q + " AND id = ?", (ticket_id,)) if ticket_id is not None
                                     else con.execute(q + " ORDER BY created_at"))]
        if ticket_id is not None and not tickets:
            t = con.execute("SELECT id, status FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
            return {"found": False, "error": f"Ticket {ticket_id} not found." if t is None else f"Ticket {ticket_id} is already closed."}
        approvals = [dict(r) for r in con.execute(
            "SELECT id, kind, ref_id, ticket_id, vendor_id, sku, size, qty, amount, status, decided_by, payment_id "
            "FROM approvals ORDER BY id")]
        drafts = [dict(r) for r in con.execute("SELECT id, ticket_id, recipient, created_by FROM drafts")]

    briefing = []
    for t in tickets:
        with closing(_connect()) as con2:
            check = closure_check(con2, t)
        entry = {"ticket": t, **check,
                 "approvals": [a for a in approvals if a["ticket_id"] == t["id"]],
                 "drafts": [d for d in drafts if d["ticket_id"] == t["id"]]}
        if t["sku"] and t["size"]:
            entry["stock"] = stock_and_restock(t["sku"], t["size"], t["qty"] or 0)
        if t["lease_id"] is not None or t["invoice_id"] is not None:
            entry["bill"] = bills_and_cash(t["lease_id"], t["invoice_id"])
        briefing.append(entry)

    overall = bills_and_cash()
    return {
        "today": desk["date_today"],
        "desk_notes": desk["notes"],
        "open_tickets": briefing,
        "approval_requests_in_progress": [a for a in approvals if a["status"] in ("pending", "approved")],
        "all_open_bills_total": overall["total_due"],
        "cash_accounts": overall["cash_accounts"],
    }


@mcp.tool(annotations=READ_ONLY)
def list_tickets() -> dict:
    """Every ticket (open and closed) with its approval requests and drafts,
    plus a simple open/resolved flag (resolved = status 'closed'). For the
    dashboard board and for checking what is already done."""
    with closing(_connect()) as con:
        tickets = [dict(r) for r in con.execute("SELECT * FROM tickets ORDER BY id")]
        approvals = [dict(r) for r in con.execute("SELECT * FROM approvals ORDER BY id")]
        drafts = [dict(r) for r in con.execute("SELECT * FROM drafts ORDER BY id")]
        today = _today(con).isoformat()
    with closing(_connect()) as con:
        checks = {t["id"]: closure_check(con, t) for t in tickets}
    for t in tickets:
        t["state"] = "resolved" if t["status"] == "closed" else "open"
        t.update(checks[t["id"]])
        t["approvals"] = [a for a in approvals if a["ticket_id"] == t["id"]]
        t["drafts"] = [d for d in drafts if d["ticket_id"] == t["id"]]
    return {"today": today, "tickets": tickets,
            "approvals_without_ticket": [a for a in approvals if a["ticket_id"] is None]}


# --- Agent write tools (no money moves) --------------------------------------


@mcp.tool(annotations=WRITES)
def request_payment_approval(kind: Literal["invoice", "rent"], ref_id: int, requested_by: str,
                             reason: str, ticket_id: int | None = None) -> dict:
    """Ask the human to approve paying one vendor invoice (kind='invoice',
    ref_id=invoices.id) or one month's rent (kind='rent', ref_id=leases.id).

    The amount is read from the database, never supplied by the agent. Refuses
    if the bill doesn't exist, is already paid, or already has a pending or
    approved request. Nothing is paid here; payment needs human approval.
    """
    with closing(_connect(write=True)) as con:
        if kind == "invoice":
            r = con.execute("SELECT amount, status FROM invoices WHERE id = ?", (ref_id,)).fetchone()
            if r is None:
                return {"ok": False, "error": f"Invoice {ref_id} not found."}
            if r["status"] != "open":
                return {"ok": False, "error": f"Invoice {ref_id} is '{r['status']}', not open."}
            amount = r["amount"]
        else:
            r = con.execute("SELECT monthly_rent FROM leases WHERE id = ?", (ref_id,)).fetchone()
            if r is None:
                return {"ok": False, "error": f"Lease {ref_id} not found."}
            amount = r["monthly_rent"]
        if ticket_id is None:
            ticket_id = _ticket_for(con, kind, ref_id)
        if ticket_id is not None and con.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
            return {"ok": False, "error": f"Ticket {ticket_id} not found."}
        rej = con.execute("SELECT id FROM approvals WHERE kind = ? AND ref_id = ? AND status = 'rejected' "
                          "AND ticket_id IS ?", (kind, ref_id, ticket_id)).fetchone()
        if rej is not None:
            return {"ok": False, "error": f"The human rejected this {kind} (approval {rej['id']}). Don't request it again; "
                                          "leave the ticket for the human / next desk run."}
        existing = _active_approval(con, kind, ref_id)
        if existing is not None:
            return {"ok": False, "error": f"Approval request {existing['id']} for this {kind} is already {existing['status']}.",
                    "approval_id": existing["id"]}
        cur = con.execute(
            """INSERT INTO approvals (kind, ref_id, ticket_id, amount, reason, status, requested_by, requested_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (kind, ref_id, ticket_id, amount, reason, requested_by, _now()),
        )
        con.commit()
        balance = _balance(con)
        return {"ok": True, "approval_id": cur.lastrowid, "status": "pending", "kind": kind,
                "ref_id": ref_id, "amount": amount, "pay_from": PAY_FROM_ACCOUNT,
                "balance_now": balance, "cash_covers_it": balance is not None and balance >= amount}


@mcp.tool(annotations=WRITES)
def request_purchase_order(vendor_id: int, sku: str, size: str, qty: int, requested_by: str,
                           reason: str, ticket_id: int | None = None) -> dict:
    """Ask the human to approve a restock purchase order.

    Cost = qty x pricing.unit_cost (read from the database). Refuses if the
    vendor, SKU/size or ticket doesn't exist, qty < 1, or the vendor has an
    open unpaid invoice (shop rule 3). Expected arrival = desk.date_today +
    vendors.lead_days (shop rule 2). Nothing is paid here.
    """
    if qty < 1:
        return {"ok": False, "error": "qty must be at least 1."}
    with closing(_connect(write=True)) as con:
        today = _today(con)
        v = con.execute("SELECT id, name, lead_days FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if v is None:
            return {"ok": False, "error": f"Vendor {vendor_id} not found."}
        if con.execute("SELECT 1 FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone() is None:
            return {"ok": False, "error": f"No inventory row for {sku} size {size}."}
        p = con.execute("SELECT unit_cost FROM pricing WHERE sku = ?", (sku,)).fetchone()
        if p is None:
            return {"ok": False, "error": f"No pricing row for {sku}."}
        if ticket_id is not None and con.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
            return {"ok": False, "error": f"Ticket {ticket_id} not found."}
        dup = con.execute(
            "SELECT id, status, qty FROM approvals WHERE kind = 'purchase_order' AND sku = ? AND size = ? "
            "AND status IN ('pending', 'approved', 'paid') AND (ticket_id IS ? OR ? IS NULL)",
            (sku, size, ticket_id, ticket_id)).fetchone()
        rej = con.execute(
            "SELECT id FROM approvals WHERE kind = 'purchase_order' AND sku = ? AND size = ? AND qty = ? "
            "AND status = 'rejected' AND ticket_id IS ?", (sku, size, qty, ticket_id)).fetchone()
        if rej is not None:
            return {"ok": False, "error": f"The human rejected this purchase order (approval {rej['id']}). Don't request "
                                          "it again; leave the ticket for the human / next desk run."}
        if dup is not None:
            return {"ok": False, "error": f"A purchase order for {sku} {size} already exists (approval {dup['id']}, "
                                          f"{dup['qty']} units, {dup['status']}). Don't order it again.",
                    "approval_id": dup["id"], "status": dup["status"]}
        blocking = _open_invoices_for_vendor(con, vendor_id, today)
        if blocking:
            return {"ok": False, "error": f"{v['name']} will not ship: open unpaid invoice(s) {[b['id'] for b in blocking]}.",
                    "blocking_invoices": blocking}
        amount = round(qty * p["unit_cost"], 2)
        cur = con.execute(
            """INSERT INTO approvals (kind, ref_id, ticket_id, vendor_id, sku, size, qty, amount, reason,
                                      status, requested_by, requested_at)
               VALUES ('purchase_order', NULL, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (ticket_id, vendor_id, sku, size, qty, amount, reason, requested_by, _now()),
        )
        con.commit()
        balance = _balance(con)
        return {"ok": True, "approval_id": cur.lastrowid, "status": "pending", "vendor": v["name"],
                "sku": sku, "size": size, "qty": qty, "unit_cost": p["unit_cost"], "amount": amount,
                "expected_arrival": date.fromordinal(today.toordinal() + v["lead_days"]).isoformat(),
                "balance_now": balance, "cash_covers_it": balance is not None and balance >= amount}


@mcp.tool(annotations=WRITES)
def save_customer_draft(ticket_id: int, recipient: str, message: str, created_by: str) -> dict:
    """Save a draft message for a ticket's customer on the board. It is never
    sent (shop rule 8). Refuses if the ticket doesn't exist."""
    with closing(_connect(write=True)) as con:
        if con.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
            return {"ok": False, "error": f"Ticket {ticket_id} not found."}
        cur = con.execute(
            "INSERT INTO drafts (ticket_id, recipient, message, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (ticket_id, recipient, message, created_by, _now()),
        )
        con.commit()
        return {"ok": True, "draft_id": cur.lastrowid, "ticket_id": ticket_id, "status": "draft (not sent)"}


@mcp.tool(annotations=WRITES)
def update_ticket_status(ticket_id: int, status: Literal["open", "in_progress", "waiting_approval", "closed"],
                         note: str, updated_by: str) -> dict:
    """Set a ticket's status and append a dated note explaining why. Refuses
    if the ticket doesn't exist."""
    with closing(_connect(write=True)) as con:
        t = con.execute("SELECT status, notes FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is not None and t["status"] == "closed":
            return {"ok": False, "error": f"Ticket {ticket_id} is already closed."}
        if t is None:
            return {"ok": False, "error": f"Ticket {ticket_id} not found."}
        if status == "closed":
            check = closure_check(con, con.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone())
            if not check["ready_to_close"]:
                return {"ok": False, "error": f"Ticket {ticket_id} can't close yet: {'; '.join(check['close_blockers'])}.",
                        **check}
        line = f"[{_today(con).isoformat()} {updated_by}: {t['status']} -> {status}] {note}"
        notes = f"{t['notes']}\n{line}" if t["notes"] else line
        con.execute("UPDATE tickets SET status = ?, notes = ? WHERE id = ?", (status, notes, ticket_id))
        con.commit()
        return {"ok": True, "ticket_id": ticket_id, "old_status": t["status"], "new_status": status}


# --- Human-only tools (never given to an agent) -------------------------------


@mcp.tool(annotations=WRITES)
def approve_request(approval_id: int, decision: Literal["approve", "reject"], decided_by: str) -> dict:
    """HUMAN ONLY. Record the human's decision on a pending approval request."""
    with closing(_connect(write=True)) as con:
        a = con.execute("SELECT status FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if a is None:
            return {"ok": False, "error": f"Approval request {approval_id} not found."}
        if a["status"] != "pending":
            return {"ok": False, "error": f"Approval request {approval_id} is already {a['status']}."}
        new = "approved" if decision == "approve" else "rejected"
        con.execute("UPDATE approvals SET status = ?, decided_by = ?, decided_at = ? WHERE id = ?",
                    (new, decided_by, _now(), approval_id))
        con.commit()
        return {"ok": True, "approval_id": approval_id, "status": new, "decided_by": decided_by}


@mcp.tool(annotations=MOVES_MONEY)
def pay_approved_payment(approval_id: int) -> dict:
    """HUMAN ONLY (runs right after the human approves). Pays one approved request.

    Re-checks everything at pay time: the request exists and is 'approved'
    by a human, the bill is still unpaid, and checking can cover it (shop
    rule 5: never negative). In one transaction it writes a payments row,
    lowers the cash balance, and marks the invoice paid or moves the lease's
    next_due forward one month. Purchase orders are paid but stock is not
    added (goods arrive after the vendor's lead days).
    """
    con = _connect(write=True)
    try:
        con.execute("BEGIN IMMEDIATE")  # lock first, so the cash check and the write can't interleave
        today = _today(con)
        a = con.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if a is None:
            return {"ok": False, "error": f"Approval request {approval_id} not found."}
        if a["status"] == "paid":
            return {"ok": False, "error": f"Approval request {approval_id} is already paid (payment {a['payment_id']})."}
        if a["status"] != "approved" or not a["decided_by"]:
            return {"ok": False, "error": f"Approval request {approval_id} is '{a['status']}'; it must be approved by a human first."}

        if a["kind"] == "invoice":
            inv = con.execute("SELECT amount, status FROM invoices WHERE id = ?", (a["ref_id"],)).fetchone()
            if inv is None or inv["status"] != "open":
                return {"ok": False, "error": f"Invoice {a['ref_id']} is not open; nothing to pay."}
            amount = inv["amount"]
        elif a["kind"] == "rent":
            lease = con.execute("SELECT monthly_rent, next_due FROM leases WHERE id = ?", (a["ref_id"],)).fetchone()
            if lease is None:
                return {"ok": False, "error": f"Lease {a['ref_id']} not found."}
            amount = lease["monthly_rent"]
        else:
            amount = a["amount"]

        balance = _balance(con)
        if balance is None:
            return {"ok": False, "error": f"Cash account '{PAY_FROM_ACCOUNT}' not found."}
        if balance < amount:
            return {"ok": False, "error": f"Refused: {PAY_FROM_ACCOUNT} has ${balance:,.2f}, payment is ${amount:,.2f}. "
                                          "Balances can never go negative.",
                    "balance": balance, "amount": amount}

        cur = con.execute(
            "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES (?, ?, ?, ?, ?, ?)",
            (a["kind"], a["ref_id"] if a["kind"] != "purchase_order" else approval_id, amount,
             PAY_FROM_ACCOUNT, today.isoformat(), a["decided_by"]),
        )
        new_balance = round(balance - amount, 2)
        con.execute("UPDATE cash_accounts SET balance = ?, date = ? WHERE name = ?",
                    (new_balance, today.isoformat(), PAY_FROM_ACCOUNT))
        updated = {}
        if a["kind"] == "invoice":
            con.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (a["ref_id"],))
            updated = {"invoice_id": a["ref_id"], "invoice_status": "paid"}
        elif a["kind"] == "rent":
            nxt = _add_month(date.fromisoformat(lease["next_due"])).isoformat()
            con.execute("UPDATE leases SET next_due = ? WHERE id = ?", (nxt, a["ref_id"]))
            updated = {"lease_id": a["ref_id"], "next_due_was": lease["next_due"], "next_due_now": nxt}
        con.execute("UPDATE approvals SET status = 'paid', payment_id = ? WHERE id = ?", (cur.lastrowid, approval_id))
        con.commit()
        return {"ok": True, "payment_id": cur.lastrowid, "kind": a["kind"], "amount": amount,
                "account": PAY_FROM_ACCOUNT, "balance_before": balance, "balance_after": new_balance,
                "approved_by": a["decided_by"], "paid_at": today.isoformat(), **updated}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


ensure_tables()

if __name__ == "__main__":
    mcp.run(show_banner=False)
