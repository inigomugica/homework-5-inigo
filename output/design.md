# Campus Customs — Agent Command Deck (design)

The dashboard (`frontend/`, React + Vite + TypeScript) is the boss-of-the-future's panel for the agent team. Start it with `npm run dev` in `frontend/`; it opens http://localhost:5173 and talks to the FastAPI backend at http://localhost:8000.

## The dashboard loop
1. **Pick** a ticket on the left board.
2. **Engage** the team. The Boss starts, and the agents hand work to each other.
3. **Watch** the network light up and the transmissions stream in while the run is going. The page polls `/api/events` about once a second.
4. **Read** the result: the Boss's final call, one debrief card per agent, and any customer drafts.
5. **Authorize** any payment or purchase order on the right. Approve & Pay moves the money.
6. **See** the checking balance count down, and the ticket's status change on the board.
7. **Fresh desk on every start:** the backend resets the database when it starts (rule 7), so there's no Reset button.

**Problem 9 additions:**
- **▶ RUN THE DESK** queues every open ticket, and runs go one at a time.
- **Approve & Pay** pays, then sends the team back to finish that ticket.
- **Reject** never re-queues (no loops).
- Each ticket shows **"To close: …"** (what's still missing), which turns green when it's done.
- Closed tickets move to a **Closed tickets** section.

Every step maps to a problem 7 route: `/api/tickets`, `/api/tickets/{id}/run`, `/api/events`, `/api/approvals/{id}` and `/api/cash`. `/api/reset` still exists, but the backend start does the reset.

## Layout
A three-column deck under a top bar. The columns follow the order of the work: *what's on the desk* → *what the team is doing* → *what needs me*.

| Zone | What's there | Why |
|---|---|---|
| **Top bar** | Brand, shop date (`desk.date_today`), backend link light, team state and queue, **checking balance**, **▶ Run the desk** | The things a boss glances at constantly are always visible. The date is the shop's date, not the computer's (rule 1). |
| **Left: Ticket board** | Open tickets as cards (ID, subject, type, requester, status or QUEUED pill, approval and draft flags), with a **Closed tickets** section below | Lists all tickets, not just three, so new ones appear automatically. Finished work moves out of the way. |
| **Centre: Mission** | The selected ticket's header and **Engage Team** button; the **agent network**; the **transmission feed**; the Boss's **final call**; **agent debrief** cards; **customer drafts** | One place to start a run and follow it start to finish. |
| **Right: Authorization dock** | Every request waiting for a human: kind, amount, the agent's reason, who asked, the **balance after paying**, Approve & Pay / Reject | Money decisions are physically separate from the agents' work. The only button that moves cash sits apart, so nobody clicks it by accident. |

## How agents read differently
Each agent has its own **colour, glyph and call sign**, used the same way everywhere: the network, the feed and the debrief.

| Agent | Call sign | Glyph | Colour |
|---|---|---|---|
| Boss | COMMAND | ◆ | gold |
| Inventory | STOCK | ▣ | cyan |
| Accounting | LEDGER | $ | green (money) |
| Facilities | SPACE | ⌂ | violet |
| Customer Service | VOICE | ✦ | pink |
| You (human) | HUMAN | ● | white |

- **Agent network:** the five agents sit on a pentagon with every pair linked, which shows the full connectivity. During a run:
  - the agent speaking now **pulses**;
  - the links in the current handoff chain **light up and flow**;
  - agents that have taken part stay bright, and the others stay dim.
- **Transmission feed:**
  - each line carries the time, the agent's call sign, a verb (ONLINE, TOOL, HANDOFF, SAYS, NEEDS APPROVAL, REFUSED…) and a plain-English sentence;
  - raw tool names are translated, so `check_stock_and_restock` becomes "checks stock and restock options";
  - lines are **indented by handoff depth**, so Boss → Facilities → Accounting reads like a conversation tree;
  - refusals and fact-check retries show in amber, and limit stops in red.
- **Debrief:** one card per agent that worked the ticket, showing its final status, its summary, and the MCP tools it used as small chips.
- **Token meter:** a bar under the network fills toward the 60,000-token limit for the run, so cost is visible while it happens.

## How resolved tickets show up
- **Status pills** follow the ticket statuses: OPEN and IN PROGRESS in cyan, AWAITING APPROVAL in gold, RESOLVED in green. A ticket being worked shows a pink **TEAM WORKING** pill and a glowing edge.
- When a run finishes, the board refreshes. If the Boss **closed** the ticket, it gets a green **RESOLVED stamp** that drops onto the card, and its Engage button turns into "RESOLVED ✓".
- **Resolved means closed.** A ticket that is only waiting for your approval stays gold, not green. Why: approving money is the step that actually finishes the work.
- **Finishing after approval:** after you approve, engage the team on that ticket again. The Boss sees the payment marked as paid and closes the ticket. No ticket is closed by the dashboard itself.

## How cash shows up
- **Where:** the checking balance sits top right in a green glass panel, because it's the number the boss cares about most.
- **After a payment:** the number **counts down** to the new balance over about a second, and a red **▼ $amount** flashes under it, so the drop is unmistakable.
- **Low cash:** below $500 the whole panel turns red as a warning.
- **Before you approve:** each authorization card shows the **balance after paying**. If cash can't cover it, the card turns red and says "not enough cash". The backend refuses it anyway (rule 5), and if you approve, the refusal appears as a message.
- **Cash only goes out** (rule 6), so the panel only ever goes down, and its subtitle says "cash out only".

## Creative choices that make it feel special
- **Mission-control look:** a deep-space background with a faint grid and scanlines, frosted-glass panels, neon edges, the Orbitron display face for headings, and JetBrains Mono for all numbers and telemetry. It reads like a cockpit, and the numbers stay perfectly aligned.
- **A living network:** watching the pentagon light up as the Boss hands work to Facilities and then Accounting makes the multi-agent idea tangible. You *see* delegation instead of reading about it.
- **Radio-style transmissions:** agents "come online", "hand off" and "report", which turns a log into a story that's fun to watch.
- **Ceremony around money:** approvals live in their own "Authorization" dock with a deliberate "APPROVE & PAY" button and a balance preview. The moment you sign is the moment the number drops.
- **Satisfying finish:** the RESOLVED stamp animation gives a small "job done" moment.
- **Calm by default:** nothing moves unless the team is working. Animations are switched off when the operating system asks for reduced motion.
- **Honest UI:** the deck only shows what the backend returns, the same facts the agents saw. It never makes up a number, and it never offers a way to pay without approval.
- **Fresh after reset:** runs from before the latest reset are hidden. When a ticket shows an earlier run, the feed is labelled "last run" with its time.
