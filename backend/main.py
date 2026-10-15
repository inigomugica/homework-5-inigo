"""FastAPI backend for the Campus Customs dashboard.

Start (from backend/):  uvicorn main:app --reload --port 8000
Every start (including a --reload restart) resets the working database to the original.
Docs: http://localhost:8000/docs

Every shop fact is read through the MCP server (mcp_client / agents). The
only non-MCP pieces are the audit file (agent events) and the database
reset, which copies the untouched original over the working copy.
"""

import asyncio
import json
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import agents
import approvals
import audit
import mcp_client
from models import DecisionIn, RunOut

DATA = Path(__file__).resolve().parents[1] / "data"
ORIGINAL_DB = DATA / "campus_customs.db"
WORKING_DB = DATA / "campus_customs_new.db"

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Every start is a fresh desk (shop rule 7): copy the original over the working copy first.
    shutil.copyfile(ORIGINAL_DB, WORKING_DB)
    audit.log(run_id="startup", ticket_id=None, agent="system", chain=["system"], event="db_reset",
              detail={"action": "database reset to original on backend start"})
    # One MCP connection for the API's lifetime, so routes answer fast.
    async with mcp_client.client() as c:
        mcp_client.shared = c
        yield
        mcp_client.shared = None


app = FastAPI(title="Campus Customs desk", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# One agent run (or reset) at a time: runs are long and share one database.
_busy = asyncio.Lock()


@app.get("/api/tickets")
async def list_tickets():
    """Every ticket with its status, open/resolved, approval requests and drafts."""
    return await mcp_client.call("list_tickets")


@app.post("/api/tickets/{ticket_id}/run", response_model=RunOut)
async def run_ticket(ticket_id: int):
    """Run the agent team (Boss first) on one ticket. Returns the Boss's final reply."""
    tickets = (await mcp_client.call("list_tickets"))["tickets"]
    ticket = next((t for t in tickets if t["id"] == ticket_id), None)
    if ticket is None:
        raise HTTPException(404, f"Ticket {ticket_id} not found.")
    if ticket["state"] == "resolved":
        raise HTTPException(409, f"Ticket {ticket_id} is already resolved.")
    if _busy.locked():
        raise HTTPException(409, "The team is already working; try again when it finishes.")
    async with _busy:
        reply, run_id = await agents.run_ticket_with_id(ticket_id)
    return RunOut(ticket_id=ticket_id, run_id=run_id, reply=reply)


@app.get("/api/events")
async def recent_events(after: int = Query(0, ge=0, description="return events after this line number"),
                        limit: int = Query(200, ge=1, le=1000),
                        ticket_id: int | None = None, run_id: str | None = None):
    """Recent agent events from the audit trail: what each agent said and which tools it used.

    Poll with ?after=<next> to get only new events."""
    if not audit.AUDIT_PATH.exists():
        return {"next": 0, "events": []}
    lines = audit.AUDIT_PATH.read_text(encoding="utf-8").splitlines()
    events = []
    for n, line in enumerate(lines[after:], start=after + 1):
        if not line.strip():
            continue
        e = json.loads(line)
        if ticket_id is not None and e.get("ticket_id") != ticket_id:
            continue
        if run_id is not None and e.get("run_id") != run_id:
            continue
        events.append({"line": n, **e})
    return {"next": len(lines), "events": events[-limit:]}


@app.post("/api/approvals/{approval_id}")
async def decide_approval(approval_id: int, body: DecisionIn = DecisionIn()):
    """The human's click. 'approve' records the approval and pays it (cash, payments,
    invoice/lease updated by the MCP pay tool); 'reject' just records the decision."""
    out = await approvals.decide(approval_id, body.decision)
    payment = out.get("payment")
    if payment is None and not out["decision"].get("ok"):
        raise HTTPException(409, out["decision"].get("error", "Not allowed."))
    if payment is not None and not payment.get("ok"):
        raise HTTPException(409, payment.get("error", "Payment refused."))  # e.g. not enough cash
    return out


@app.get("/api/cash")
async def checking_balance():
    """Current checking balance from cash_accounts."""
    bills = await mcp_client.call("check_bills_and_cash")
    acct = next((a for a in bills["cash_accounts"] if a["name"] == "checking"), None)
    if acct is None:
        raise HTTPException(404, "No checking account.")
    return {"account": "checking", "balance": acct["balance"], "as_of": acct["date"], "today": bills["today"]}


@app.post("/api/reset")
async def reset_database():
    """Copy the original database over the working copy (shop rule 7). The audit trail is kept."""
    if _busy.locked():
        raise HTTPException(409, "Can't reset while the team is working.")
    async with _busy:
        shutil.copyfile(ORIGINAL_DB, WORKING_DB)
    audit.log(run_id="reset", ticket_id=None, agent="system", chain=["system"], event="db_reset",
              detail={"action": "database reset to original"})
    return {"ok": True, "message": "Working database reset to the original."}
