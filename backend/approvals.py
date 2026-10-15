"""The human approval path: the only code that calls approve_request and
pay_approved_payment. It talks to the same MCP server the agents use, so
the payment rules (approved by a human, enough cash, update the tables)
are enforced in one place. The dashboard will call this; for now use:

    python backend/approvals.py <approval_id> approve|reject
"""

import asyncio
import os
import sys

import audit
import mcp_client

HUMAN_APPROVER = os.getenv("HUMAN_APPROVER", "Inigo Mugica Ortiz")


async def decide(approval_id: int, decision: str, decided_by: str = HUMAN_APPROVER) -> dict:
    """Record the human's decision; if approved, pay it straight away."""
    result = await mcp_client.call("approve_request", {"approval_id": approval_id, "decision": decision,
                                                       "decided_by": decided_by})
    out = {"decision": result}
    # Approved earlier but refused for lack of cash: approving again retries the payment.
    retry = decision == "approve" and not result.get("ok") and "already approved" in result.get("error", "")
    if decision == "approve" and (result.get("ok") or retry):
        out["payment"] = await mcp_client.call("pay_approved_payment", {"approval_id": approval_id})
    audit.log(run_id="human", ticket_id=None, agent="human", chain=["human"], event="human_decision",
              detail={"approval_id": approval_id, "decided_by": decided_by, **out})
    return out


if __name__ == "__main__":
    print(asyncio.run(decide(int(sys.argv[1]), sys.argv[2])))
