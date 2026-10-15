# Campus Customs — Agent Command Deck

React + Vite + TypeScript dashboard for the agent team. Design notes: [`../output/design.md`](../output/design.md).

```bash
npm install
npm run dev        # opens http://localhost:5173
```

Needs the backend running on http://localhost:8000. Start it from `../backend` with `uvicorn main:app --reload --port 8000`. To point the dashboard elsewhere, copy `.env.example` to `.env` and change `VITE_API_URL`.

- `src/App.tsx`: the dashboard loop (load, run + live polling, approvals, reset)
- `src/api.ts`: calls to the problem 7 routes
- `src/agents.ts`: each agent's colour, glyph and call sign, and plain-English event lines
- `src/components/`: ticket board, agent network, transmission feed, debrief, authorization dock, cash display
