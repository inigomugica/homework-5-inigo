"""Run the agent team from the command line.

    python backend/run_team.py --ticket 102     # one ticket
    python backend/run_team.py --desk --reset   # full run, after resetting the database (shop rule 7)
"""

import argparse
import asyncio
import shutil
from pathlib import Path

import agents

DATA = Path(__file__).resolve().parents[1] / "data"


def reset_database() -> None:
    """Copy the untouched original over the working copy."""
    shutil.copyfile(DATA / "campus_customs.db", DATA / "campus_customs_new.db")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticket", type=int)
    ap.add_argument("--desk", action="store_true")
    ap.add_argument("--reset", action="store_true", help="reset the working database first")
    a = ap.parse_args()
    if a.reset:
        reset_database()
    reply = asyncio.run(agents.run_desk() if a.desk else agents.run_ticket(a.ticket))
    print(reply.model_dump_json(indent=2))
