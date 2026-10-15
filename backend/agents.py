"""The Campus Customs agent team: five PydanticAI agents on gpt-6-luna via Portkey.

- Every shop fact and every database write goes through the MCP server
  (mcp_server/server.py) over stdio. There is no second tools layer.
- Each agent sees only the MCP tools its role needs (least privilege).
  approve_request and pay_approved_payment are given to NO agent: only the
  human path in approvals.py calls them.
- Full connectivity: every agent has `delegate(to_agent, task)` and can hand
  work to any other agent. Handoffs are bounded by depth and cannot loop
  back to an agent already in the chain.
- One shared usage budget per ticket run covers every agent and handoff.
- Every loop step is appended to output/audit_trail.json.

Entry points: run_ticket(ticket_id), run_desk(), run_agent(name, task, deps).
"""

import json
import os
import re
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastmcp.client.transports import StdioTransport
from openai import AsyncOpenAI
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelRequest, ToolCallPart, ToolReturnPart, TextPart, UserPromptPart
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RunUsage, UsageLimits

import audit
from models import AGENT_NAMES, AgentName, AgentReply, TeamDeps

HERE = Path(__file__).resolve().parent
HW = HERE.parent
load_dotenv(HW / ".env")
load_dotenv(HW.parent / ".env")  # fallback: a .env one folder up
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

PROMPTS = HERE / "prompts"
MODEL_NAME = "gpt-6-luna"

# --- Limits (token use and loop safety) ---------------------------------------
MAX_HANDOFF_DEPTH = 3            # boss -> a -> b -> c, no deeper
OUTPUT_RETRIES = 2               # extra model calls allowed when a reply fails validation
# One budget for a whole ticket run, shared by every agent and handoff in it.
TICKET_LIMITS = UsageLimits(request_limit=30, tool_calls_limit=35, total_tokens_limit=80_000)
DESK_LIMITS = UsageLimits(request_limit=60, tool_calls_limit=80, total_tokens_limit=150_000)

_key = os.environ["PORTKEY_API_KEY"]  # never printed, logged or hard-coded
_client = AsyncOpenAI(
    api_key=_key,
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.portkey.ai/v1"),
    default_headers={"x-portkey-api-key": _key},
    max_retries=4,  # retry transient provider errors (5xx, timeouts) with backoff before giving up
)
_model = OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=_client))
_settings = OpenAIResponsesModelSettings(openai_reasoning_effort="low")

# --- MCP: one connection, filtered per agent -----------------------------------

READ_TOOLS = {"get_desk_briefing", "check_bills_and_cash", "check_stock_and_restock"}
AGENT_TOOLS: dict[AgentName, set[str]] = {
    "boss": READ_TOOLS | {"list_tickets", "update_ticket_status"},
    "inventory": {"check_stock_and_restock", "get_desk_briefing"},
    "accounting": READ_TOOLS | {"request_payment_approval", "request_purchase_order"},
    "facilities": {"check_bills_and_cash", "get_desk_briefing"},
    "customer_service": READ_TOOLS | {"save_customer_draft"},
}
HUMAN_ONLY_TOOLS = {"approve_request", "pay_approved_payment"}
assert not any(HUMAN_ONLY_TOOLS & t for t in AGENT_TOOLS.values())

# Write tools take the acting agent's name; the harness fills it in so an agent can't sign as someone else.
IDENTITY_ARG = {"request_payment_approval": "requested_by", "request_purchase_order": "requested_by",
                "save_customer_draft": "created_by", "update_ticket_status": "updated_by"}


async def _audited_call(ctx: RunContext[TeamDeps], call_tool, name: str, args: dict):
    d = ctx.deps
    if name not in AGENT_TOOLS[d.agent]:  # belt and braces: the filter already hides it
        raise ModelRetry(f"Tool {name} is not available to {d.agent}.")
    if name in IDENTITY_ARG:
        args = {**args, IDENTITY_ARG[name]: d.agent}
    # Requests made while working a ticket are always linked to that ticket.
    if name in ("request_payment_approval", "request_purchase_order") and args.get("ticket_id") is None and d.ticket_id is not None:
        args = {**args, "ticket_id": d.ticket_id}
    common = dict(run_id=d.run_id, ticket_id=d.ticket_id, agent=d.agent, chain=d.chain, step=ctx.run_step)
    audit.log(**common, event="mcp_call", detail={"tool": name, "args": args})
    result = await call_tool(name, args)
    audit.log(**common, event="mcp_result", detail={"tool": name, "result": result},
              usage=_usage(ctx.usage))
    return result


_mcp = MCPToolset(
    StdioTransport(command=sys.executable, args=[str(HW / "mcp_server" / "server.py")], cwd=str(HW)),
    process_tool_call=_audited_call,
    tool_error_behavior="retry",
)


def _toolset_for(agent: AgentName):
    allowed = AGENT_TOOLS[agent]
    return _mcp.filtered(lambda ctx, tool_def: tool_def.name in allowed)


def _usage(u: RunUsage) -> dict[str, int]:
    return {"requests": u.requests, "tool_calls": u.tool_calls,
            "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
            "total_tokens": u.input_tokens + u.output_tokens}


# --- The five agents -------------------------------------------------------------

def _build(name: AgentName) -> Agent[TeamDeps, AgentReply]:
    agent = Agent(
        _model,
        name=name,
        deps_type=TeamDeps,
        output_type=AgentReply,
        model_settings=_settings,
        toolsets=[_toolset_for(name)],
        tools=[delegate],
        retries=OUTPUT_RETRIES,
    )

    @agent.instructions
    def prompt() -> str:  # re-read each run, so prompt edits apply without a restart
        return ((PROMPTS / "shop_rules.md").read_text(encoding="utf-8") + "\n\n"
                + (PROMPTS / f"{name}.md").read_text(encoding="utf-8"))

    @agent.instructions
    def context(ctx: RunContext[TeamDeps]) -> str:
        d = ctx.deps
        others = ", ".join(a for a in AGENT_NAMES if a != d.agent and a not in d.chain)
        hops = MAX_HANDOFF_DEPTH - d.depth
        return (f"You are `{d.agent}`. Handoff chain so far: {' -> '.join(d.chain)}. "
                f"Ticket in focus: {d.ticket_id if d.ticket_id is not None else 'none (whole desk)'}. "
                f"Your MCP tools: {', '.join(sorted(AGENT_TOOLS[d.agent]))}. "
                + (f"You may delegate to: {others} ({hops} handoff level(s) left)." if hops > 0 and others
                   else "You cannot delegate further; answer with what you have."))

    agent.output_validator(_no_invented_facts)
    return agent


async def delegate(ctx: RunContext[TeamDeps], to_agent: AgentName, task: str) -> str:
    """Hand a specific task to another agent and get its reply back.

    Use it when the task belongs to another role (see the shop rules). Give
    the ticket id and the exact facts you already have from tools. You
    cannot delegate to yourself or to an agent already in the handoff chain.
    """
    d = ctx.deps
    if to_agent == d.agent:
        return "Refused: you cannot delegate to yourself."
    if to_agent in d.chain:
        return f"Refused: {to_agent} is already in the handoff chain ({' -> '.join(d.chain)}); reply to them instead."
    if d.depth >= MAX_HANDOFF_DEPTH:
        return f"Refused: handoff depth limit ({MAX_HANDOFF_DEPTH}) reached. Answer with what you have."
    audit.log(run_id=d.run_id, ticket_id=d.ticket_id, agent=d.agent, chain=d.chain, step=ctx.run_step,
              event="handoff", detail={"to": to_agent, "task": task})
    child = TeamDeps(agent=to_agent, run_id=d.run_id, ticket_id=d.ticket_id,
                     chain=[*d.chain, to_agent], desk_run=d.desk_run)
    reply = await run_agent(to_agent, task, child, usage=ctx.usage)
    audit.log(run_id=d.run_id, ticket_id=d.ticket_id, agent=d.agent, chain=d.chain, step=ctx.run_step,
              event="handoff_result", detail={"from": to_agent, "reply": reply.model_dump()}, usage=_usage(ctx.usage))
    return reply.model_dump_json()


# --- Guard against invented facts ------------------------------------------------

_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _seen_numbers(ctx: RunContext[TeamDeps]) -> set[float]:
    """Every number that reached this agent from a tool result, a handoff reply or its task."""
    seen: set[float] = set()
    for msg in ctx.messages:
        if not isinstance(msg, ModelRequest):
            continue
        for part in msg.parts:
            if isinstance(part, (ToolReturnPart, UserPromptPart)):
                text = part.content if isinstance(part.content, str) else json.dumps(part.content, default=str)
                seen.update(float(n) for n in _NUM.findall(text.replace(",", "")))
    return seen


def _no_invented_facts(ctx: RunContext[TeamDeps], reply: AgentReply) -> AgentReply:
    seen = _seen_numbers(ctx)
    text = " ".join([reply.summary, reply.next_step or ""])
    bad_money = [m for m in _MONEY.findall(text) if float(m.replace(",", "")) not in seen]
    bad_ids = [i for i in [*reply.ticket_ids, *reply.approval_ids, *reply.draft_ids] if float(i) not in seen]
    if bad_money or bad_ids:
        d = ctx.deps
        audit.log(run_id=d.run_id, ticket_id=d.ticket_id, agent=d.agent, chain=d.chain, step=ctx.run_step,
                  event="output_retry", detail={"unverified_amounts": bad_money, "unverified_ids": bad_ids})
        raise ModelRetry(
            f"These values did not come from any tool result in this run: amounts {bad_money}, ids {bad_ids}. "
            "Only report amounts and IDs returned by a tool (call one if needed), or say they are unknown.")
    return reply


AGENTS: dict[AgentName, Agent[TeamDeps, AgentReply]] = {n: _build(n) for n in AGENT_NAMES}


# --- Running -------------------------------------------------------------------------

async def run_agent(name: AgentName, task: str, deps: TeamDeps, *, usage: RunUsage | None = None,
                    limits: UsageLimits | None = None) -> AgentReply:
    """Run one agent's loop, logging every step. Handoffs reuse the caller's usage budget."""
    agent = AGENTS[name]
    common = dict(run_id=deps.run_id, ticket_id=deps.ticket_id, agent=name, chain=deps.chain)
    audit.log(**common, event="run_start", detail={"task": task})
    try:
        limits = limits or (DESK_LIMITS if deps.desk_run else TICKET_LIMITS)
        async with agent.iter(task, deps=deps, usage=usage, usage_limits=limits) as run:
            async for node in run:
                if Agent.is_call_tools_node(node):
                    parts = node.model_response.parts
                    audit.log(**common, step=run.ctx.state.run_step, event="model_response", detail={
                        "tool_calls": [{"tool": p.tool_name, "args": p.args} for p in parts if isinstance(p, ToolCallPart)],
                        "text": " ".join(p.content for p in parts if isinstance(p, TextPart)),
                    }, usage=_usage(run.usage))
        reply = run.result.output
        audit.log(**common, event="run_end", detail={"reply": reply.model_dump()}, usage=_usage(run.usage))
        return reply
    except UsageLimitExceeded as e:
        audit.log(**common, event="limit_hit", detail={"error": str(e)})
        return AgentReply(status="blocked", summary=f"Stopped by the token/step limit: {e}",
                          next_step="A human should review this ticket.")
    except Exception as e:  # e.g. the model provider failed even after retries; never crash the desk
        audit.log(**common, event="error", detail={"error": f"{type(e).__name__}: {e}"})
        return AgentReply(status="blocked", summary=f"{name} stopped: the model provider returned an error ({type(e).__name__}).",
                          next_step="Engage the team on this ticket again.")


async def run_ticket(ticket_id: int) -> AgentReply:
    return (await run_ticket_with_id(ticket_id))[0]


async def run_ticket_with_id(ticket_id: int) -> tuple[AgentReply, str]:
    deps = TeamDeps(agent="boss", run_id=uuid.uuid4().hex[:12], ticket_id=ticket_id, chain=["boss"])
    task = (f"Work ticket {ticket_id}. Start with get_desk_briefing(ticket_id={ticket_id}), route the work, "
            "and make the final call. If its approvals are already paid, finish the remaining steps and close it. "
            "Remember: payments only ever go to the human for approval.")
    async with _mcp:
        return await run_agent("boss", task, deps, usage=RunUsage(), limits=TICKET_LIMITS), deps.run_id


async def run_desk() -> AgentReply:
    deps = TeamDeps(agent="boss", run_id=uuid.uuid4().hex[:12], chain=["boss"], desk_run=True)
    task = ("Run today's desk: read get_desk_briefing, work every open ticket in priority order, "
            "and make the final calls. Payments only ever go to the human for approval.")
    async with _mcp:
        return await run_agent("boss", task, deps, usage=RunUsage(), limits=DESK_LIMITS)
