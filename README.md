# Campus Customs — Multi-Agent Operation (Homework 5)

A five-agent team that runs the Campus Customs shop's ticket board:
- **Boss**, **Inventory**, **Accounting**, **Facilities** and **Customer Service** (PydanticAI, `gpt-6-luna` via Portkey);
- an **MCP server** (FastMCP) that is the only way the agents read or change the shop database;
- a **FastAPI backend**;
- a **React + Vite + TypeScript dashboard** where a human runs the desk, watches the agents and approves payments.

Full system description: [`output/harness.md`](output/harness.md) · dashboard design: [`output/design.md`](output/design.md) · run results: [`output/desk_tickets.html`](output/desk_tickets.html).

## Layout
```
.env.example        copy to .env and add your key (never commit .env)
.mcp.json           registers the MCP server with a coding assistant (Windows path; see note below)
requirements.txt    Python dependencies
AI_prompts.md       prompt log, one section per problem
data/               campus_customs.db (original, never modified) + campus_customs_new.db (working copy)
mcp_server/         server.py: the MCP tools
backend/            main.py (FastAPI), models.py, agents.py, prompts/ (one file per agent + shop_rules.md)
frontend/           the React dashboard
output/             harness, design, desk tickets page, results, audit trail, GitHub URL
```

## Setup (once)
Requires **Python 3.12+** and **Node 20+**. Run from the repo root:

```bash
python -m venv .venv
.venv\Scripts\activate                      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                      # macOS/Linux: cp .env.example .env
```
Edit `.env` and set `PORTKEY_API_KEY`. The key is read from `.env` only and is never printed or committed.

```bash
cd frontend
npm install
cd ..
```

## 1. Copy the original database to the working copy (clean run)
`data/campus_customs.db` is the untouched original. Everything (MCP server, agents, backend) reads and writes only **`data/campus_customs_new.db`**. To start clean, copy the original over the working copy:

```bash
copy data\campus_customs.db data\campus_customs_new.db       # macOS/Linux: cp data/campus_customs.db data/campus_customs_new.db
```
The committed `campus_customs_new.db` holds the state after the problem 9 run (checking $152.00), so copy it fresh before you run anything yourself.

## 2. Start the MCP server
The agents and the backend start the MCP server themselves (stdio), so you only need this to check it or to call the tools from a coding assistant:

```bash
python mcp_server/server.py
```
`.mcp.json` registers it as `campus-customs`. It uses the Windows venv path `.venv/Scripts/python.exe`; on macOS/Linux change it to `.venv/bin/python`. Tools: see [`mcp_server/README.md`](mcp_server/README.md).

## 3. Start the FastAPI backend (terminal 1)
```bash
cd backend
uvicorn main:app --reload --port 8000
```
- **API:** http://localhost:8000, with docs at http://localhost:8000/docs.
- **Every start resets the working database to the original**, including a `--reload` restart after a code change.

## 4. Start the React board (terminal 2)
```bash
cd frontend
npm run dev
```
This opens **http://localhost:5173**. Click **▶ RUN THE DESK**, watch the agents, and click **Approve & Pay** or **Reject** on each request in the Authorization panel. Approving sends the team back to finish that ticket.

## 5. Reset the database before a full three-ticket run
Shop rule 7: always start a full run from the original values. Any of these works:
- **Restart the backend** (step 3). It resets on start, which is the simplest option.
- With the backend running, call the reset route:
  ```bash
  curl -X POST http://localhost:8000/api/reset
  ```
- Stop the backend and copy the file as in step 1.

After a reset: checking is **$3,400.00**, tickets 101, 102 and 103 are open, and there are no approvals or payments.

## Command-line alternative (no dashboard)
```bash
python backend/run_team.py --ticket 102             # run the team on one ticket
python backend/run_team.py --desk --reset           # full desk run after a reset
python backend/approvals.py <approval_id> approve   # the human approval (pays it)
```

## Safety, in short
- **Payments:** agents can only *request* payments and purchase orders. Only the human's Approve click pays, and the pay tool refuses anything that would make a balance negative.
- **Data:** every fact comes from the database through MCP.
- **Audit:** every agent step is appended to `output/audit_trail.json`.

Details are in [`output/harness.md`](output/harness.md).
