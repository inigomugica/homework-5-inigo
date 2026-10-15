"""Data types for the Campus Customs agent team.

Shop facts are NOT modelled here: they live in the database and reach the
agents only through the MCP server. These types describe the team itself:
who the agents are, what each run carries, what an agent must hand back,
and what one audit-trail line looks like.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
AGENT_NAMES: tuple[AgentName, ...] = ("boss", "inventory", "accounting", "facilities", "customer_service")


@dataclass
class TeamDeps:
    """Carried through every agent run, including runs started by a handoff."""
    agent: AgentName                      # the agent running right now
    run_id: str                           # one id for the whole ticket run (all handoffs share it)
    ticket_id: int | None = None          # the ticket being worked, if any
    chain: list[AgentName] = field(default_factory=list)  # who handed work to whom, e.g. ["boss", "inventory"]
    desk_run: bool = False                # whole-desk run (bigger shared budget) vs. one ticket

    @property
    def depth(self) -> int:
        return len(self.chain) - 1


class AgentReply(BaseModel):
    """What every agent must return, to the human or to the agent that handed it work."""
    status: Literal["done", "needs_approval", "blocked", "needs_info"] = Field(
        description="done = finished; needs_approval = waiting on a human approval request; "
                    "blocked = a rule or missing stock/cash stops it; needs_info = a fact is missing.")
    summary: str = Field(description="Plain-language result. Every $ amount, date and ID must come from a tool result in this run.")
    ticket_ids: list[int] = Field(default_factory=list, description="Tickets this reply is about.")
    approval_ids: list[int] = Field(default_factory=list, description="Approval requests created or found (from tool results only).")
    draft_ids: list[int] = Field(default_factory=list, description="Customer drafts created (from tool results only).")
    next_step: str | None = Field(default=None, description="What should happen next and who should do it.")


class AuditEvent(BaseModel):
    """One line in output/audit_trail.json (JSON Lines: one event per line, append-only)."""
    ts: str                               # real wall-clock time the step happened
    run_id: str
    ticket_id: int | None
    agent: AgentName | Literal["human", "system"]
    chain: list[str]                      # handoff path at this step
    step: int | None = None               # loop step number inside this agent's run
    event: Literal["run_start", "model_response", "mcp_call", "mcp_result", "handoff",
                   "handoff_result", "output_retry", "run_end", "limit_hit", "error", "human_decision", "db_reset"]
    detail: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, int] | None = None   # tokens so far for the whole ticket run


# --- API types (dashboard <-> FastAPI) -------------------------------------------

class DecisionIn(BaseModel):
    """Body of POST /api/approvals/{id}: the human's click."""
    decision: Literal["approve", "reject"] = "approve"


class RunOut(BaseModel):
    """What POST /api/tickets/{id}/run returns once the team finishes."""
    ticket_id: int
    run_id: str
    reply: AgentReply
